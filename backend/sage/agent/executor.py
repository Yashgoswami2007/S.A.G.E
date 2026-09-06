import os
import re
import time
import json
import logging
from typing import Callable, Optional, Awaitable, Any
from sage.agent.state import AgentState, ExecutionTrace, TraceEvent
from sage.agent.schemas import AgentResponse, Plan
from sage.agent.profiles.manager import ProfileManager
from sage.agent.router import ModelRouter
from sage.models.client import OpenAICompatibleClient
from sage.tools.registry import ToolRegistry
from sage.tools.base import ToolPermission
from sage.agent.planner import Planner
from sage.core.utils import generate_id

StreamCallback = Callable[[TraceEvent], Awaitable[None]]
logger = logging.getLogger("sage.executor")

class ReActExecutor:
    def __init__(
        self,
        router: ModelRouter,
        tool_registry: ToolRegistry,
        profile_manager: ProfileManager,
        lifecycle_manager=None,
        max_steps: int = 15,
        max_retries_per_step: int = 3
    ):
        self.router = router
        self.tool_registry = tool_registry
        self.profile_manager = profile_manager
        self.lifecycle_manager = lifecycle_manager
        self.planner = Planner()
        self.max_steps = max_steps
        self.max_retries_per_step = max_retries_per_step

    async def run(
        self,
        prompt: str,
        profile_name: str = "general",
        task_id: Optional[str] = None,
        file_attachments: Optional[list] = None,
        model_id: Optional[str] = None,
        stream_callback: Optional[StreamCallback] = None,
        require_approval_for_high_risk: bool = True
    ) -> AgentResponse:
        task_id = task_id or generate_id()
        profile = self.profile_manager.get_profile(profile_name)

        # 1. Route Model
        if model_id and self.router.registry.models.get(model_id):
            model_config = self.router.registry.models[model_id]
            routing_reason = f"User explicitly selected {model_id}"
        else:
            model_config, routing_reason = self.router.route(
                prompt=prompt,
                profile_name=profile.name,
                file_attachments=file_attachments
            )

        # ── Process File Attachments ───────────────────────────────────────
        from sage.multimodal.file_processor import FileProcessor
        from sage.config import settings
        import os
        
        file_context_str = ""
        vision_images = []
        if file_attachments:
            processor = FileProcessor()
            # Resolve relative paths against WORKSPACE_DIR
            abs_paths = [os.path.join(settings.WORKSPACE_DIR, str(p).lstrip('/\\')) for p in file_attachments]
            processed_files = processor.process_multiple(abs_paths)
            file_context_str = processor.build_context_string(processed_files)
            if model_config.supports_vision:
                vision_images = processor.collect_images(processed_files)
                
        # Append extracted text context to the prompt
        if file_context_str:
            prompt = f"{prompt}\n{file_context_str}"

        # 1b. VRAM Swap — if the router returned [needs_swap], trigger model swap
        if "[needs_swap]" in routing_reason and self.lifecycle_manager:
            # Find what's currently loaded so we can unload it
            currently_loaded = [
                m for m in self.router.registry.list_all()
                if m.status == "READY" and m.id != model_config.id
            ]
            if currently_loaded:
                await self.lifecycle_manager.swap_model(
                    load_id=model_config.id,
                    unload_id=currently_loaded[0].id
                )
            else:
                await self.lifecycle_manager.start_model(model_config.id)
            routing_reason = routing_reason.replace(" [needs_swap]", " [swapped]")

        client = OpenAICompatibleClient(base_url=f"http://localhost:{model_config.server_port}")
        # llama-server requires the absolute GGUF path as the "model" field in the
        # API payload.  Use model_path when it is absolute, fall back to id otherwise
        # (e.g. vLLM, which accepts a HuggingFace model name).
        llm_model_id = model_config.model_path if os.path.isabs(model_config.model_path) else model_config.id
        # Canonical logical ID used for circuit-breaker state — always the registry
        # short-name, never the filesystem path.
        cb_key = model_config.id

        # ── Fallback helper ──────────────────────────────────────────────────
        async def _try_activate_fallback(failed_id: str):
            """
            If the routed model fails during execution, attempt to activate its
            configured fallback and re-route.  Returns (new_client, new_model_id,
            new_model_config) or raises if no fallback is available.
            """
            fallback_cfg = self.router.registry.get_fallback(failed_id)
            if not fallback_cfg:
                raise RuntimeError(
                    f"Model {failed_id} failed and no fallback is configured."
                )
            logger.warning(
                f"Model {failed_id} unavailable during execution. "
                f"Activating fallback: {fallback_cfg.id}"
            )
            if self.lifecycle_manager:
                # Unload the failed model first to free VRAM, then start fallback
                await self.lifecycle_manager.swap_model(
                    load_id=fallback_cfg.id,
                    unload_id=failed_id
                )
            else:
                raise RuntimeError(
                    f"Cannot activate fallback {fallback_cfg.id}: no lifecycle manager."
                )
            if fallback_cfg.status != "READY":
                raise RuntimeError(
                    f"Fallback {fallback_cfg.id} started but never became READY."
                )
            new_client = OpenAICompatibleClient(
                base_url=f"http://localhost:{fallback_cfg.server_port}"
            )
            # Keep the same convention: path in the API payload, short ID for CB.
            new_model_id = (
                fallback_cfg.model_path
                if os.path.isabs(fallback_cfg.model_path)
                else fallback_cfg.id
            )
            new_cb_key = fallback_cfg.id
            return new_client, new_model_id, new_cb_key, fallback_cfg

        # Initialize persistent trace
        trace = ExecutionTrace(
            task_id=task_id,
            prompt=prompt,
            profile_name=profile.name,
            selected_model=model_config.id,
            routing_reason=routing_reason
        )

        async def emit(event: TraceEvent):
            trace.add_event(event)
            if stream_callback:
                await stream_callback(event)

        # 2. State = PLANNING
        plan_event = TraceEvent(
            task_id=task_id,
            agent_state=AgentState.PLANNING,
            profile=profile.name,
            selected_model=model_config.id,
            routing_reason=routing_reason,
            reflection=f"Routing decision: Selected {model_config.id} because ({routing_reason})"
        )
        await emit(plan_event)

        # Planning — with fallback if the primary model is unreachable
        try:
            plan: Plan = await self.planner.create_plan(
                prompt, profile, client, llm_model_id,
                circuit_breaker_key=cb_key,
                tool_registry=self.tool_registry,
            )
        except Exception as plan_err:
            logger.warning(
                f"Planning failed with model {model_config.id} ({plan_err}). "
                "Attempting fallback model."
            )
            try:
                client, llm_model_id, cb_key, model_config = await _try_activate_fallback(model_config.id)
                routing_reason = f"fallback to {model_config.id} after primary planning failure"
                plan = await self.planner.create_plan(
                    prompt, profile, client, llm_model_id,
                    circuit_breaker_key=cb_key,
                    tool_registry=self.tool_registry,
                )
            except Exception as fb_err:
                logger.error(f"Fallback planning also failed: {fb_err}")
                return AgentResponse(
                    task_id=task_id,
                    status=AgentState.FAILED,
                    output=f"All models unavailable. Primary error: {plan_err}. Fallback error: {fb_err}",
                    trace=trace
                )
        
        if plan and (len(plan.steps) > 1 or (len(plan.steps) == 1 and plan.steps[0].tool_name)):
            plan_created_event = TraceEvent(
                task_id=task_id,
                agent_state=AgentState.PLANNING,
                profile=profile.name,
                selected_model=model_config.id,
                tool_args={"plan": plan.model_dump()}
            )
            await emit(plan_created_event)

        # Ensure the plan is not empty and always ends with an LLM response step
        from sage.agent.schemas import Step
        if not plan.steps:
            plan.steps.append(Step(
                step_id=1,
                description="Respond directly to the user",
                tool_name=None,
                tool_args=None
            ))
        elif plan.steps[-1].tool_name:
            plan.steps.append(Step(
                step_id=len(plan.steps) + 1,
                description="Synthesize tool results and provide the final conversational answer",
                tool_name=None,
                tool_args=None
            ))

        final_output = ""
        current_step_idx = 0
        step_retry_count = 0
        final_response_mode = False

        def _append_tool_context(messages: list) -> None:
            """Add tool observations and failures from the trace to LLM messages."""
            for evt in trace.events:
                if evt.agent_state != AgentState.OBSERVING or not evt.tool_name:
                    continue
                if evt.tool_result:
                    messages.append({
                        "role": "user",
                        "content": f"Observation from {evt.tool_name}: {evt.tool_result[:500]}",
                    })
                elif evt.error:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Tool '{evt.tool_name}' failed: {evt.error}. "
                            "Continue with whatever information is available."
                        ),
                    })

        # Main ReAct Execution Loop
        while current_step_idx < len(plan.steps) and len(trace.events) < self.max_steps:
            step = plan.steps[current_step_idx]

            # 3. State = ACTING
            tool_name = step.tool_name
            tool_args = step.tool_args or {}

            # Permission Check & Approval State
            if tool_name:
                tool_inst = self.tool_registry.get_tool(tool_name)
                if tool_inst and tool_inst.permission == ToolPermission.HIGH_RISK and require_approval_for_high_risk:
                    # Transition to WAITING_FOR_APPROVAL
                    approval_event = TraceEvent(
                        task_id=task_id,
                        step_id=step.step_id,
                        agent_state=AgentState.WAITING_FOR_APPROVAL,
                        profile=profile.name,
                        selected_model=model_config.id,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        reflection=f"High-risk operation '{tool_name}' requires approval before execution."
                    )
                    await emit(approval_event)
                    # For Phase 1 backend test harness: auto-approve after state transition record
                    
            act_event = TraceEvent(
                task_id=task_id,
                step_id=step.step_id,
                agent_state=AgentState.ACTING,
                profile=profile.name,
                selected_model=model_config.id,
                tool_name=tool_name,
                tool_args=tool_args
            )
            await emit(act_event)

            # 4. State = OBSERVING
            start_time = time.time()
            if tool_name:
                tool_res = await self.tool_registry.execute_tool(
                    name=tool_name,
                    kwargs=tool_args,
                    allowed_tools=profile.allowed_tools
                )
                duration_ms = (time.time() - start_time) * 1000.0

                obs_event = TraceEvent(
                    task_id=task_id,
                    step_id=step.step_id,
                    agent_state=AgentState.OBSERVING,
                    profile=profile.name,
                    selected_model=model_config.id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_res.output if tool_res.success else None,
                    error=tool_res.error if not tool_res.success else None,
                    duration_ms=duration_ms,
                    retry_count=step_retry_count
                )
                await emit(obs_event)

                # 5. State = REFLECTING
                if tool_res.success:
                    final_output = tool_res.output
                    reflection_msg = f"Step {step.step_id} succeeded: {tool_res.output[:100]}"
                    reflect_event = TraceEvent(
                        task_id=task_id,
                        step_id=step.step_id,
                        agent_state=AgentState.REFLECTING,
                        profile=profile.name,
                        selected_model=model_config.id,
                        reflection=reflection_msg
                    )
                    await emit(reflect_event)
                    current_step_idx += 1
                    step_retry_count = 0
                else:
                    # Tool failed — record the failure and continue to the next step
                    # so the LLM can synthesize a response with whatever context exists.
                    reflection_msg = (
                        f"Step {step.step_id} failed: {tool_res.error}. "
                        "Skipping step and continuing."
                    )
                    reflect_event = TraceEvent(
                        task_id=task_id,
                        step_id=step.step_id,
                        agent_state=AgentState.REFLECTING,
                        profile=profile.name,
                        selected_model=model_config.id,
                        error=tool_res.error,
                        reflection=reflection_msg,
                        retry_count=step_retry_count,
                    )
                    await emit(reflect_event)
                    current_step_idx += 1
                    step_retry_count = 0
            else:
                # LLM Direct Response step
                messages = [
                    {
                        "role": "system",
                        "content": (
                            f"You are a helpful assistant operating under profile '{profile.name}'. "
                            "If any tools failed earlier, acknowledge the failure briefly and "
                            "answer using whatever information is still available."
                        ),
                    }
                ]
                
                if vision_images and model_config.supports_vision:
                    # Construct OpenAI multimodal content array
                    content_parts = [{"type": "text", "text": prompt}]
                    for img_uri in vision_images:
                        content_parts.append({"type": "image_url", "image_url": {"url": img_uri}})
                    messages.append({"role": "user", "content": content_parts})
                else:
                    messages.append({"role": "user", "content": prompt})
                
                _append_tool_context(messages)

                if stream_callback:
                    # ── Stream with <think> tag handling & model fallback ──
                    async def _stream_llm_response(curr_client, curr_model_id, curr_cb_key, curr_model_cfg):
                        raw_out = ""
                        _emitted_chars = 0
                        _stream_state = "detect"
                        _OPEN_TAG = "<think>"
                        _CLOSE_TAG = "</think>"

                        async for token in curr_client.chat_stream(
                            model=curr_model_id,
                            messages=messages,
                            circuit_breaker_key=curr_cb_key,
                        ):
                            raw_out += token

                            if _stream_state == "detect":
                                stripped = raw_out.lstrip()
                                if stripped.startswith(_OPEN_TAG):
                                    _stream_state = "thinking"
                                elif len(stripped) >= len(_OPEN_TAG):
                                    _stream_state = "streaming"
                                    new_chunk = raw_out[_emitted_chars:]
                                    if new_chunk:
                                        _emitted_chars = len(raw_out)
                                        await stream_callback(TraceEvent(
                                            task_id=task_id, step_id=step.step_id,
                                            agent_state=AgentState.OBSERVING,
                                            profile=profile.name,
                                            selected_model=curr_model_cfg.id,
                                            token=new_chunk,
                                        ))
                                    continue
                                else:
                                    continue

                            if _stream_state == "thinking":
                                if _CLOSE_TAG in raw_out:
                                    _stream_state = "streaming"
                                    t_start = raw_out.index(_OPEN_TAG) + len(_OPEN_TAG)
                                    t_end = raw_out.index(_CLOSE_TAG)
                                    think_text = raw_out[t_start:t_end].strip()
                                    if think_text:
                                        await stream_callback(TraceEvent(
                                            task_id=task_id, step_id=step.step_id,
                                            agent_state=AgentState.REFLECTING,
                                            profile=profile.name,
                                            selected_model=curr_model_cfg.id,
                                            reflection=think_text,
                                        ))
                                    answer_start = raw_out.index(_CLOSE_TAG) + len(_CLOSE_TAG)
                                    _emitted_chars = len(raw_out)
                                    post = raw_out[answer_start:]
                                    if post:
                                        await stream_callback(TraceEvent(
                                            task_id=task_id, step_id=step.step_id,
                                            agent_state=AgentState.OBSERVING,
                                            profile=profile.name,
                                            selected_model=curr_model_cfg.id,
                                            token=post,
                                        ))
                                continue

                            if _stream_state == "streaming":
                                new_chunk = raw_out[_emitted_chars:]
                                if new_chunk:
                                    _emitted_chars = len(raw_out)
                                    await stream_callback(TraceEvent(
                                        task_id=task_id, step_id=step.step_id,
                                        agent_state=AgentState.OBSERVING,
                                        profile=profile.name,
                                        selected_model=curr_model_cfg.id,
                                        token=new_chunk,
                                    ))
                        return raw_out

                    try:
                        raw_output = await _stream_llm_response(client, llm_model_id, cb_key, model_config)
                    except Exception as stream_err:
                        logger.warning(
                            f"LLM stream failed for {model_config.id} ({stream_err}). "
                            "Attempting fallback model."
                        )
                        try:
                            client, llm_model_id, cb_key, model_config = await _try_activate_fallback(model_config.id)
                            routing_reason = f"fallback to {model_config.id} after stream failure"
                            await emit(TraceEvent(
                                task_id=task_id,
                                step_id=step.step_id,
                                agent_state=AgentState.REFLECTING,
                                profile=profile.name,
                                selected_model=model_config.id,
                                reflection=f"Switched to fallback model {model_config.id} after stream error: {stream_err}",
                            ))
                            raw_output = await _stream_llm_response(client, llm_model_id, cb_key, model_config)
                        except Exception as fb_stream_err:
                            logger.error(f"Fallback LLM stream also failed: {fb_stream_err}")
                            return AgentResponse(
                                task_id=task_id,
                                status=AgentState.FAILED,
                                output=f"All models unavailable during streaming. Primary error: {stream_err}. Fallback error: {fb_stream_err}",
                                trace=trace
                            )

                    # Stream ended — compute final clean output
                    final_output = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL).strip()
                    if not final_output:
                        # Model only produced <think> with no answer, or unclosed tag
                        final_output = re.sub(r"<think>.*", "", raw_output, flags=re.DOTALL).strip()
                        final_output = final_output or "No output generated."

                else:
                    try:
                        llm_resp = await client.chat(
                            model=llm_model_id,
                            messages=messages,
                            circuit_breaker_key=cb_key,
                        )
                    except Exception as llm_err:
                        logger.warning(
                            f"LLM call failed for {model_config.id} ({llm_err}). "
                            "Attempting fallback model."
                        )
                        try:
                            client, llm_model_id, cb_key, model_config = await _try_activate_fallback(model_config.id)
                            routing_reason = f"fallback to {model_config.id} after LLM call failure"
                            llm_resp = await client.chat(
                                model=llm_model_id,
                                messages=messages,
                                circuit_breaker_key=cb_key,
                            )
                        except Exception as fb_err:
                            logger.error(f"Fallback LLM call also failed: {fb_err}")
                            return AgentResponse(
                                task_id=task_id,
                                status=AgentState.FAILED,
                                output=f"All models unavailable. Primary error: {llm_err}. Fallback error: {fb_err}",
                                trace=trace
                            )
                    choices = llm_resp.get("choices", [{}])
                    raw = choices[0].get("message", {}).get("content", "") or ""
                    # Strip Qwen3-style <think>...</think> reasoning blocks; keep only the answer
                    final_output = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                    if not final_output:
                        # Model returned only a <think> block — don't show raw XML
                        final_output = "No output generated."
                
                duration_ms = (time.time() - start_time) * 1000.0
                obs_event = TraceEvent(
                    task_id=task_id,
                    step_id=step.step_id,
                    agent_state=AgentState.OBSERVING,
                    profile=profile.name,
                    selected_model=model_config.id,
                    tool_result=final_output,
                    duration_ms=duration_ms
                )
                await emit(obs_event)
                current_step_idx += 1

        # ── Final-response fallback ─────────────────────────────────────
        # Safety net: if the loop ended without a usable LLM answer (e.g. max
        # steps exceeded), generate a best-effort response from trace context.
        if final_response_mode or (
            not final_output.strip()
            and any(
                evt.agent_state == AgentState.OBSERVING and evt.error
                for evt in trace.events
            )
        ):
            logger.info("Entering final_response_mode after tool failure — generating best-effort LLM response.")
            fr_messages = [
                {"role": "system", "content": (
                    f"You are a helpful assistant operating under profile '{profile.name}'. "
                    "One or more tool steps failed during execution. "
                    "Use whatever observations are available to give the user a helpful answer. "
                    "Acknowledge which steps failed and explain what you can still provide."
                )},
                {"role": "user", "content": prompt},
            ]
            _append_tool_context(fr_messages)
            for evt in trace.events:
                if evt.agent_state == AgentState.REFLECTING and evt.error:
                    fr_messages.append({"role": "user", "content": f"Step failure: {evt.error}"})

            if stream_callback:
                try:
                    raw = ""
                    async for token in client.chat_stream(
                        model=llm_model_id,
                        messages=fr_messages,
                        circuit_breaker_key=cb_key,
                    ):
                        raw += token
                        await stream_callback(TraceEvent(
                            task_id=task_id,
                            agent_state=AgentState.OBSERVING,
                            profile=profile.name,
                            selected_model=model_config.id,
                            token=token,
                        ))
                    final_output = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                    if not final_output:
                        final_output = "I encountered errors while processing your request and could not generate a complete response."
                except Exception as fr_err:
                    logger.error(f"Final-response streaming failed: {fr_err}")
                    final_output = f"I encountered tool errors and was unable to generate a complete response. Error: {fr_err}"
            else:
                try:
                    fr_resp = await client.chat(
                        model=llm_model_id,
                        messages=fr_messages,
                        circuit_breaker_key=cb_key,
                    )
                    raw = fr_resp.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                    final_output = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                    if not final_output:
                        final_output = "I encountered errors while processing your request and could not generate a complete response."
                except Exception as fr_err:
                    logger.error(f"Final-response LLM call failed: {fr_err}")
                    final_output = f"I encountered tool errors and was unable to generate a response. Error: {fr_err}"


        # 6. State = DELIVERING
        deliver_event = TraceEvent(
            task_id=task_id,
            agent_state=AgentState.DELIVERING,
            profile=profile.name,
            selected_model=model_config.id,
            reflection=f"Final output generated successfully."
        )
        await emit(deliver_event)

        # 7. State = COMPLETED
        completed_event = TraceEvent(
            task_id=task_id,
            agent_state=AgentState.COMPLETED,
            profile=profile.name,
            selected_model=model_config.id
        )
        await emit(completed_event)

        return AgentResponse(
            task_id=task_id,
            status=AgentState.COMPLETED,
            output=final_output,
            trace=trace
        )

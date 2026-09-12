export type PlanStep = {
  id: number;
  description: string;
  tool?: string;
};

export type AgentEvent =
  | { type: "PLAN_CREATED"; plan: { summary: string; steps: PlanStep[] } }
  | { type: "TOOL_CALL"; step_id: number; tool_name: string; tool_args: Record<string, any> }
  | { type: "TOOL_RESULT"; step_id: number; tool_name: string; success: boolean; output: string; error?: string }
  | { type: "THINKING"; content: string }
  | { type: "FILE_CREATED"; path: string; size_bytes: number }
  | { type: "FILE_MODIFIED"; path: string; diff_summary: string }
  | { type: "COMMAND_STARTED"; command: string; step_id: number }
  | { type: "COMMAND_FINISHED"; exit_code: number; stdout: string; stderr: string }
  | { type: "SANDBOX_STARTED"; sandbox_id: string; language: string; code: string }
  | { type: "SANDBOX_FINISHED"; sandbox_id: string; exit_code: number; stdout: string; stderr: string; duration_ms: number; files_created: string[] }
  | { type: "DOCUMENT_GENERATED"; path: string; doc_type: string; size_bytes: number }
  | { type: "ERROR"; message: string; recoverable: boolean }
  | { type: "CONFIRMATION_REQUIRED"; action: string; description: string; request_id: string; tool_args?: Record<string, any> }
  | { type: "FINAL"; content: string }
  | { type: "TOKEN"; token: string }
  | { type: "TOOL_SYNTHESIS_PROGRESS"; stage: string; message: string; attempt?: number; max_attempts?: number; tool_name?: string; tool_factory_id?: string };

export function parseAgentEvent(line: string): AgentEvent | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) return null;
  const payload = trimmed.slice(5).trim();
  if (!payload || payload === "[DONE]") return null;
  
  try {
    return JSON.parse(payload) as AgentEvent;
  } catch {
    return null;
  }
}

export function SageMark({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <img
      src="/sage-logo.png"
      alt="SAGE"
      className={className}
      draggable={false}
      loading="eager"
    />
  );
}

export function SageWordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <SageMark className="h-5 w-5 text-primary" />
      <span className="font-serif text-lg tracking-tight">SAGE</span>
    </span>
  );
}

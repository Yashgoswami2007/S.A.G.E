export function SageMark({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <path d="M12 3v18" />
        <path d="M12 8c0-2.2 1.9-4 4.2-4 .3 2.6-1.6 4.7-4.2 5" />
        <path d="M12 13c0-2.2-1.9-4-4.2-4C7.5 11.6 9.4 13.7 12 14" />
        <path d="M12 18c0-2.2 1.9-4 4.2-4 .3 2.6-1.6 4.7-4.2 5" />
      </g>
    </svg>
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

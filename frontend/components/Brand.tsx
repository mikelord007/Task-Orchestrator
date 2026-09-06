import Link from "next/link";

export default function Brand({ compact = false, href = "/" }: { compact?: boolean; href?: string }) {
  return (
    <Link href={href} aria-label="Task Orchestrator home" className="inline-flex items-center">
      {compact ? (
        <img src="/brand/task-orchestrator-mark.svg" alt="" width="32" height="32" className="h-8 w-8" />
      ) : (
        <>
          <img src="/brand/task-orchestrator-mark.svg" alt="" width="32" height="32" className="h-8 w-8 sm:hidden" />
          <img src="/brand/task-orchestrator-lockup.svg" alt="" width="252" height="32" className="hidden h-8 w-auto sm:block" />
        </>
      )}
    </Link>
  );
}

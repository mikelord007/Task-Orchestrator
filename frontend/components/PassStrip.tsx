/**
 * One mark per trial, in trial order. Reading three marks left to right tells
 * you the difference between "passes" and "passes sometimes", which is the
 * whole reason trials exist.
 */
export default function PassStrip({ passed }: { passed: boolean[] }) {
  if (passed.length === 0) return <span className="text-fg-mute">—</span>;
  const stable = passed.every(Boolean);
  const flaky = !stable && passed.some(Boolean);
  return (
    <span
      className="inline-flex items-center gap-1"
      title={
        stable
          ? "Passed in every trial (stable)"
          : flaky
            ? "Passed in some trials only (flaky, excluded from the stable set)"
            : "Failed in every trial"
      }
    >
      <span className="sr-only">{passed.map((ok) => ok ? "pass" : "fail").join(", ")}</span>
      {passed.map((ok, i) => (
        <span
          key={i}
          aria-hidden="true"
          className={`inline-block h-3 w-3 border ${ok ? "border-fg bg-fg" : "border-fail bg-fail"}`}
        />
      ))}
      {flaky ? <span className="ml-1 font-mono text-[9px] font-bold uppercase text-drift">flaky</span> : null}
    </span>
  );
}

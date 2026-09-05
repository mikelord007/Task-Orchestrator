/**
 * One mark per repeat, in repeat order. Reading three marks left to right tells
 * you the difference between "passes" and "passes sometimes", which is the
 * whole reason repeats exist.
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
          ? "Passed in every repeat (stable)"
          : flaky
            ? "Passed in some repeats only (flaky, excluded from the stable set)"
            : "Failed in every repeat"
      }
    >
      {passed.map((ok, i) => (
        <span
          key={i}
          className={`inline-block h-3 w-3 text-center text-[10px] leading-3 ${
            ok ? "text-pass" : "text-fail"
          }`}
        >
          {ok ? "✓" : "✗"}
        </span>
      ))}
      {flaky ? <span className="ml-0.5 text-[10px] text-drift">flaky</span> : null}
    </span>
  );
}

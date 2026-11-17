/** The BrewMyJob coffee cup (user feedback 2026-11-15): a steaming cup before the BMJ mark, drawn inline. */
export function CoffeeCup({ className, size = 30 }: { className?: string; size?: number }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      {/* steam */}
      <path
        d="M11 3.5c-1.2 1.4 1.2 2.6 0 4M15.5 2.5c-1.2 1.4 1.2 2.6 0 4M20 3.5c-1.2 1.4 1.2 2.6 0 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        opacity=".55"
      />
      {/* cup, coffee and handle */}
      <path d="M5 11h20v8.5a7.5 7.5 0 0 1-7.5 7.5h-5A7.5 7.5 0 0 1 5 19.5z" fill="currentColor" />
      <path d="M7 11.8h16" stroke="#fff" strokeOpacity=".35" strokeWidth="1.2" />
      <path d="M25 13.5h1.5a3.5 3.5 0 0 1 0 7H25" fill="none" stroke="currentColor" strokeWidth="2.2" />
      {/* saucer */}
      <path d="M3 29h25" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Sign-in still: an isometric hub flange drawn as engineering line work on a
 * graphite blueprint grid. Wayam orange is the only chromatic colour (Chronos
 * brand rule); everything else is graphite and white at low opacity.
 */
export function HeroDrawing({ className = "" }: { className?: string }) {
  // Isometric ellipse helper: circle of radius r on the XY plane at height z.
  const iso = (r: number, z: number, cx = 300, cy = 330) => ({ cx, cy: cy - z, rx: r * 0.866 * 1.15, ry: r * 0.5 * 1.15 });
  const disc = { r: 150, h: 34 };
  const hub = { r: 70, h: 92 };
  const bolts = Array.from({ length: 8 }, (_, i) => {
    const a = (Math.PI * 2 * i) / 8 + Math.PI / 8;
    const pr = 112;
    const x = 300 + pr * Math.cos(a) * 0.866 * 1.15;
    const y = 330 - disc.h + pr * Math.sin(a) * 0.5 * 1.15;
    return { x, y };
  });
  const top = iso(disc.r, disc.h);
  const bottom = iso(disc.r, 0);
  const hubTop = iso(hub.r, disc.h + hub.h);
  const hubBase = iso(hub.r, disc.h);
  const bore = iso(42, disc.h + hub.h);

  return (
    <svg viewBox="0 0 600 640" preserveAspectRatio="xMidYMid meet" className={className} role="img" aria-label="Isometric line drawing of a hub flange with dimension callouts">
      <defs>
        <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
          <path d="M24 0H0V24" fill="none" stroke="#ffffff" strokeOpacity="0.05" strokeWidth="1" />
        </pattern>
        <linearGradient id="glow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FF7B1C" stopOpacity="0.18" />
          <stop offset="1" stopColor="#FF7B1C" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="600" height="640" fill="#101010" />
      <rect width="600" height="640" fill="url(#grid)" />
      <ellipse cx="300" cy="340" rx="230" ry="120" fill="url(#glow)" />

      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        {/* disc */}
        <path
          d={`M${bottom.cx - bottom.rx} ${bottom.cy} A${bottom.rx} ${bottom.ry} 0 0 0 ${bottom.cx + bottom.rx} ${bottom.cy}`}
          stroke="#FF7B1C" strokeWidth="2.2"
        />
        <line x1={top.cx - top.rx} y1={top.cy} x2={bottom.cx - bottom.rx} y2={bottom.cy} stroke="#FF7B1C" strokeWidth="2.2" />
        <line x1={top.cx + top.rx} y1={top.cy} x2={bottom.cx + bottom.rx} y2={bottom.cy} stroke="#FF7B1C" strokeWidth="2.2" />
        <ellipse {...top} stroke="#FF7B1C" strokeWidth="2.2" />
        {/* bolt circle centre line and holes */}
        <ellipse cx="300" cy={330 - disc.h} rx={112 * 0.866 * 1.15} ry={112 * 0.5 * 1.15} stroke="#FFB365" strokeOpacity="0.55" strokeDasharray="10 4 2 4" strokeWidth="1" />
        {bolts.map((b, i) => (
          <ellipse key={i} cx={b.x} cy={b.y} rx="11" ry="6.3" stroke="#FFB365" strokeWidth="1.6" />
        ))}
        {/* hub */}
        <line x1={hubTop.cx - hubTop.rx} y1={hubTop.cy} x2={hubBase.cx - hubBase.rx} y2={hubBase.cy} stroke="#FF7B1C" strokeWidth="2.2" />
        <line x1={hubTop.cx + hubTop.rx} y1={hubTop.cy} x2={hubBase.cx + hubBase.rx} y2={hubBase.cy} stroke="#FF7B1C" strokeWidth="2.2" />
        <path
          d={`M${hubBase.cx - hubBase.rx} ${hubBase.cy} A${hubBase.rx} ${hubBase.ry} 0 0 0 ${hubBase.cx + hubBase.rx} ${hubBase.cy}`}
          stroke="#FF7B1C" strokeWidth="2.2"
        />
        <ellipse {...hubTop} stroke="#FF7B1C" strokeWidth="2.2" />
        <ellipse {...bore} stroke="#FFB365" strokeWidth="1.8" />
        {/* axis */}
        <line x1="300" y1={hubTop.cy - 40} x2="300" y2={bottom.cy + 30} stroke="#ffffff" strokeOpacity="0.25" strokeDasharray="14 5 3 5" strokeWidth="1" />
      </g>

      {/* dimension callouts */}
      <g fontFamily="var(--font-geist), system-ui, sans-serif" fontSize="13" fill="#ffffff" fillOpacity="0.72">
        <line x1={bottom.cx - bottom.rx} y1={bottom.cy + 46} x2={bottom.cx + bottom.rx} y2={bottom.cy + 46} stroke="#ffffff" strokeOpacity="0.45" />
        <line x1={bottom.cx - bottom.rx} y1={bottom.cy + 6} x2={bottom.cx - bottom.rx} y2={bottom.cy + 52} stroke="#ffffff" strokeOpacity="0.25" />
        <line x1={bottom.cx + bottom.rx} y1={bottom.cy + 6} x2={bottom.cx + bottom.rx} y2={bottom.cy + 52} stroke="#ffffff" strokeOpacity="0.25" />
        <text x="300" y={bottom.cy + 40} textAnchor="middle">Ø160</text>
        <line x1={hubTop.cx + hubTop.rx + 10} y1={hubTop.cy} x2={hubTop.cx + hubTop.rx + 70} y2={hubTop.cy - 46} stroke="#ffffff" strokeOpacity="0.45" />
        <text x={hubTop.cx + hubTop.rx + 74} y={hubTop.cy - 50}>Ø80 HUB · 30</text>
        {/* leader to a hole on the left, clear of the hub */}
        <line x1={bolts[4].x - 10} y1={bolts[4].y - 4} x2={bolts[4].x - 40} y2={bolts[4].y - 96} stroke="#ffffff" strokeOpacity="0.45" />
        <text x={bolts[4].x - 36} y={bolts[4].y - 102} textAnchor="end">8X Ø11 THRU EQ SP ON Ø125</text>
        <text x="40" y="70" fontSize="11" letterSpacing="2" fillOpacity="0.45">SHEET 1 OF 1 · THIRD ANGLE · MM</text>
      </g>
    </svg>
  );
}

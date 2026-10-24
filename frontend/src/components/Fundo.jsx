// Fundo: a geometria da logo do Gadosso, parada e bem apagada atrás das telas. Os "o" viram anéis finos e a cauda
// do "g" vira uma onda no peso do traço da logo. Um grão leve tira o aspecto "chapado".
export default function Fundo() {
  const tinta = (alfa) => `rgb(10 10 10 / ${(alfa * 0.55).toFixed(3)})`;
  return (
    <div className="pointer-events-none fixed inset-0 z-0" aria-hidden="true">
      <svg className="absolute inset-0 size-full" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" fill="none">
        <circle cx="1260" cy="120" r="260" stroke={tinta(0.08)} strokeWidth="1.5" />
        <circle cx="1260" cy="120" r="180" stroke={tinta(0.06)} strokeWidth="1.5" />
        <circle cx="150" cy="820" r="210" stroke={tinta(0.05)} strokeWidth="22" strokeLinecap="round" />
        <path
          d="M -80 700 C 120 640 240 640 380 690 S 640 760 820 700 S 1120 600 1300 660 S 1480 720 1560 690"
          stroke={tinta(0.07)}
          strokeWidth="22"
          strokeLinecap="round"
        />
      </svg>
      <svg className="absolute inset-0 size-full opacity-[0.05] mix-blend-multiply">
        <filter id="grao">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" stitchTiles="stitch" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grao)" />
      </svg>
    </div>
  );
}

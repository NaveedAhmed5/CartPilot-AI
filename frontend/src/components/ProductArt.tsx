import type { Product } from "../api";

/** Generated product artwork: a truck-art rosette and fringe behind a garment
 * silhouette, coloured by category. No external images needed. */

const THEMES: Record<string, { bg: string; motif: string; accent: string }> = {
  hoodies: { bg: "#232A6B", motif: "#F5B700", accent: "#D7263D" },
  "t-shirts": { bg: "#F5B700", motif: "#D7263D", accent: "#232A6B" },
  bottoms: { bg: "#1E5AA8", motif: "#9FD3F2", accent: "#F5B700" },
  outerwear: { bg: "#D7263D", motif: "#F5B700", accent: "#232A6B" },
  footwear: { bg: "#0F7F7A", motif: "#F7C6D9", accent: "#F5B700" },
  accessories: { bg: "#C2457F", motif: "#FFD8E8", accent: "#232A6B" },
};
const DEFAULT_THEME = { bg: "#232A6B", motif: "#F5B700", accent: "#D7263D" };

type Glyph = "tee" | "hoodie" | "jacket" | "pants" | "cap" | "beanie" | "bag" | "sneaker";

function glyphFor(p: Pick<Product, "name" | "category">): Glyph {
  const n = p.name.toLowerCase();
  const c = (p.category || "").toLowerCase();
  if (n.includes("beanie")) return "beanie";
  if (n.includes("bag")) return "bag";
  if (n.includes("cap") || n.includes("hat")) return "cap";
  if (c === "footwear" || n.includes("sneaker")) return "sneaker";
  if (c === "hoodies") return "hoodie";
  if (c === "outerwear") return "jacket";
  if (c === "bottoms") return "pants";
  return "tee";
}

function Silhouette({ glyph, accent }: { glyph: Glyph; accent: string }) {
  const body = { fill: "#F7F8FB", stroke: "#15162B", strokeWidth: 3, strokeLinejoin: "round" as const };
  const detail = { fill: "none", stroke: "#15162B", strokeWidth: 3, strokeLinecap: "round" as const };
  switch (glyph) {
    case "hoodie":
      return (
        <g>
          <path {...body} d="M60 58 L84 48 Q100 60 116 48 L140 58 L162 84 L144 96 L139 88 L139 158 L61 158 L61 88 L56 96 L38 84 Z" />
          <path {...body} d="M80 50 Q100 22 120 50 Q100 66 80 50 Z" />
          <path {...detail} d="M76 128 H124 V146 H76 Z" />
          <path {...detail} d="M94 62 L92 84 M106 62 L108 84" />
        </g>
      );
    case "jacket":
      return (
        <g>
          <path {...body} d="M60 56 L86 46 L100 62 L114 46 L140 56 L163 142 L146 146 L139 98 L139 158 L61 158 L61 98 L54 146 L37 142 Z" />
          <path {...detail} d="M100 62 V158" />
          <path d="M70 108 h14 v10 h-14 z M116 108 h14 v10 h-14 z" fill={accent} />
        </g>
      );
    case "pants":
      return (
        <g>
          <path {...body} d="M68 44 L132 44 L141 162 L109 162 L100 88 L91 162 L59 162 Z" />
          <path {...detail} d="M68 56 H132" />
          <path d="M64 112 h16 v20 h-16 z M120 112 h16 v20 h-16 z" fill={accent} />
        </g>
      );
    case "cap":
      return (
        <g>
          <path {...body} d="M50 118 Q50 62 100 62 Q150 62 150 118 Z" />
          <path {...body} d="M118 114 L176 112 Q172 132 140 132 L112 128 Z" />
          <circle cx="100" cy="62" r="5" fill={accent} stroke="#15162B" strokeWidth="3" />
          <path d="M80 92 l10 -10 l10 10 l10 -10 l10 10" fill="none" stroke={accent} strokeWidth="4" />
        </g>
      );
    case "beanie":
      return (
        <g>
          <path {...body} d="M58 124 Q58 66 100 66 Q142 66 142 124 Z" />
          <rect {...body} x="52" y="118" width="96" height="28" rx="6" />
          <circle cx="100" cy="58" r="12" fill={accent} stroke="#15162B" strokeWidth="3" />
          <path {...detail} d="M70 124 V144 M85 124 V144 M100 124 V144 M115 124 V144 M130 124 V144" />
        </g>
      );
    case "bag":
      return (
        <g>
          <path {...detail} d="M66 92 Q100 26 134 92" strokeWidth={5} />
          <rect {...body} x="56" y="88" width="88" height="66" rx="12" />
          <path {...detail} d="M56 112 H144" />
          <rect x="92" y="120" width="16" height="10" fill={accent} />
        </g>
      );
    case "sneaker":
      return (
        <g>
          <path {...body} d="M30 136 L36 100 L70 94 L98 112 L148 118 Q170 122 170 138 L170 148 L30 148 Z" />
          <path {...detail} d="M30 136 H170" />
          <path d="M64 104 l8 10 M76 102 l8 12 M88 106 l6 10" stroke={accent} strokeWidth="4" strokeLinecap="round" />
        </g>
      );
    default:
      return (
        <g>
          <path {...body} d="M60 56 L86 46 Q100 58 114 46 L140 56 L162 82 L144 94 L139 86 L139 158 L61 158 L61 86 L56 94 L38 82 Z" />
          <circle cx="100" cy="102" r="16" fill={accent} />
          <path d="M100 90 l4 8 9 1 -7 6 2 9 -8 -5 -8 5 2 -9 -7 -6 9 -1 z" fill="#F7F8FB" />
        </g>
      );
  }
}

export function ProductArt({ product, className }: { product: Pick<Product, "name" | "category" | "id">; className?: string }) {
  const theme = THEMES[(product.category || "").toLowerCase()] || DEFAULT_THEME;
  const glyph = glyphFor(product);
  const rotate = (product.id * 17) % 45;
  const petals = Array.from({ length: 8 }, (_, i) => i * 45 + rotate);
  return (
    <svg className={className} viewBox="0 0 200 200" role="img" aria-label={product.name} preserveAspectRatio="xMidYMid slice">
      <rect width="200" height="200" fill={theme.bg} />
      <g opacity="0.9">
        {petals.map((deg) => (
          <ellipse key={deg} cx="100" cy="52" rx="14" ry="40" fill={theme.motif} transform={`rotate(${deg} 100 100)`} opacity="0.35" />
        ))}
        <circle cx="100" cy="100" r="30" fill="none" stroke={theme.motif} strokeWidth="3" strokeDasharray="2 7" strokeLinecap="round" />
      </g>
      <Silhouette glyph={glyph} accent={theme.accent} />
      <g>
        {Array.from({ length: 10 }, (_, i) => (
          <path
            key={i}
            d={`M${i * 20} 186 l10 14 l10 -14 z`}
            fill={i % 2 ? theme.motif : theme.accent}
          />
        ))}
        <rect y="182" width="200" height="4" fill={theme.motif} />
      </g>
    </svg>
  );
}

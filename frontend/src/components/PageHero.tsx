import { type ReactNode } from "react";

type HeroChipTone = "positive" | "negative";

export type HeroChip = {
  label: string;
  value: ReactNode;
  tone?: HeroChipTone;
  hint?: string;
};

export interface PageHeroProps {
  kicker?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  chips?: HeroChip[];
  actions?: ReactNode;
  compact?: boolean;
}

export function PageHero({ kicker, title, subtitle, chips, actions, compact }: PageHeroProps) {
  return (
    <section className={`page-hero${compact ? " compact" : ""}`}>
      <div className="page-hero-copy">
        {kicker ? <div className="page-kicker">{kicker}</div> : null}
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {chips?.length ? (
        <div className="hero-meta">
          {chips.map((chip) => (
            <div
              key={chip.label}
              className={`hero-chip${chip.tone ? ` hero-chip--${chip.tone}` : ""}`}
              title={chip.hint}
            >
              <span>{chip.label}</span>
              <strong>{chip.value}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {actions ? <div className="hero-side">{actions}</div> : null}
    </section>
  );
}

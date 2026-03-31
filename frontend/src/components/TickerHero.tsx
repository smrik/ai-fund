import type { ReactNode } from "react";

type HeroStat = {
  label: string;
  value: string;
  variant?: "positive" | "negative" | "dim";
};

type HeroAction = {
  label: string;
  onClick: () => void;
  variant?: "primary" | "ghost";
  disabled?: boolean;
};

type TickerHeroProps = {
  kicker: string;
  title: string;
  description: string;
  compact?: boolean;
  stats: HeroStat[];
  actions?: HeroAction[];
  extra?: ReactNode;
};

export function TickerHero({ kicker, title, description, compact = false, stats, actions, extra }: TickerHeroProps) {
  return (
    <section className={`page-hero${compact ? " compact" : ""}`}>
      <div className="page-hero-copy">
        <div className="page-kicker">{kicker}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="hero-meta">
        {stats.map((stat) => (
          <div key={stat.label} className={`hero-chip${stat.variant ? ` hero-chip--${stat.variant}` : ""}`}>
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </div>
        ))}
      </div>
      {extra ? <div className="hero-side">{extra}</div> : null}
      {actions && actions.length ? (
        <div className="ticker-actions">
          {actions.map((action) => (
            <button
              key={action.label}
              type="button"
              className={action.variant === "primary" ? "primary-button" : "ghost-button"}
              onClick={action.onClick}
              disabled={action.disabled}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

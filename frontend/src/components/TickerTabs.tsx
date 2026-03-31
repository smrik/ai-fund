import { NavLink, useParams } from "react-router-dom";

export const tickerTabs = [
  { to: "overview", label: "Overview" },
  { to: "valuation", label: "Valuation" },
  { to: "market", label: "Market" },
  { to: "research", label: "Research" },
  { to: "audit", label: "Audit" },
];

type TickerTabsProps = {
  className?: string;
};

export function TickerTabs({ className = "" }: TickerTabsProps) {
  const { ticker = "" } = useParams();
  const classes = className ? `ticker-tabs ${className}` : "ticker-tabs";
  const tickerRoot = ticker ? `/ticker/${ticker.toUpperCase()}` : "";

  return (
    <nav className={classes} role="tablist" aria-label="Ticker sections">
      {tickerTabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={`${tickerRoot}/${tab.to}`}
          className={({ isActive }) => `ticker-tab${isActive ? " active" : ""}`}
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}

import { NavLink, Outlet, useMatch } from "react-router-dom";

export function RootLayout() {
  const tickerMatch = useMatch("/ticker/:ticker/*");
  const activeTicker = tickerMatch?.params.ticker?.toUpperCase();
  const navItems = [
    { to: "/watchlist", label: "Watchlist" },
    ...(activeTicker ? [{ to: `/ticker/${activeTicker}/overview`, label: activeTicker }] : []),
  ];

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div>
          <div className="brand-kicker">Alpha Pod</div>
          <div className="brand-title">Quote-Terminal Research</div>
        </div>
        <nav className="app-nav" aria-label="Primary">
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

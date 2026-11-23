import { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { useSession } from "../session";
import { AuthDialog } from "./AuthDialog";

export function Header() {
  const { customer, signOut } = useSession();
  const [authOpen, setAuthOpen] = useState(false);
  return (
    <header className="site-header">
      <div className="wrap header-inner">
        <Link to="/" className="wordmark" aria-label="CartPilot home">
          CartPilot
        </Link>
        <nav className="main-nav" aria-label="Main">
          <NavLink to="/" end>
            Shop
          </NavLink>
          <NavLink to="/account">My account</NavLink>
        </nav>
        <div className="header-actions">
          {customer ? (
            <>
              <span className="hello">Hi, {customer.displayName || customer.username}</span>
              <button className="btn-ghost small" onClick={signOut}>
                Sign out
              </button>
            </>
          ) : (
            <button className="btn-ghost small" onClick={() => setAuthOpen(true)}>
              Sign in
            </button>
          )}
        </div>
      </div>
      <AuthDialog open={authOpen} onClose={() => setAuthOpen(false)} />
    </header>
  );
}

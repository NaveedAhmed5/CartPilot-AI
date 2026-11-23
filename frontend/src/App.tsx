import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { ChatPanel } from "./components/ChatPanel";
import { Header } from "./components/Header";
import { Account } from "./pages/Account";
import { Admin } from "./pages/Admin";
import { Store } from "./pages/Store";
import { SessionProvider } from "./session";

function Shell() {
  const { pathname } = useLocation();
  if (pathname.startsWith("/admin")) return <Admin />;
  return (
    <>
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <Header />
      <Routes>
        <Route path="/" element={<Store />} />
        <Route path="/account" element={<Account />} />
        <Route path="*" element={<Store />} />
      </Routes>
      <ChatPanel />
    </>
  );
}

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </SessionProvider>
  );
}

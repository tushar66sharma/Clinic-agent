import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/feedback";
import { Layout } from "./components/Layout";
import { EmptyState } from "./components/ui";
import "./index.css";
import { EvaluationPage } from "./pages/EvaluationPage";
import { InboxPage } from "./pages/InboxPage";
import { NewMessagePage } from "./pages/NewMessagePage";
import { QueuesPage } from "./pages/QueuesPage";
import { SchedulePage } from "./pages/SchedulePage";
import { SystemPage } from "./pages/SystemPage";

function NotFound() {
  return (
    <div className="card">
      <EmptyState title="Page not found">
        <Link to="/" className="text-brand-700 underline">Back to the inbox</Link>
      </EmptyState>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<InboxPage />} />
            <Route path="new" element={<NewMessagePage />} />
            <Route path="queues" element={<QueuesPage />} />
            <Route path="schedule" element={<SchedulePage />} />
            <Route path="evaluation" element={<EvaluationPage />} />
            <Route path="system" element={<SystemPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  </StrictMode>,
);

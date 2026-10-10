import { Component, type ReactNode } from "react";

/** Last line of defence: a render fault shows a clear message instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main>
        <div className="notice notice--bad" role="alert">
          <div className="notice__title">Something went wrong showing this screen</div>
          <p>Your data is safe on the server. Reload the page to continue.</p>
          <div><button type="button" className="btn" onClick={() => window.location.reload()}>Reload</button></div>
        </div>
      </main>
    );
  }
}

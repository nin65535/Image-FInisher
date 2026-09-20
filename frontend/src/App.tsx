import { useEffect, useState } from "react";

import { fetchHealth } from "./api";

type ConnectionState = "checking" | "connected" | "failed";

export function App() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then(() => setConnection("connected"))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setConnection("failed");
      });
    return () => controller.abort();
  }, []);
  const labels: Record<ConnectionState, string> = {
    checking: "APIを確認中",
    connected: "API接続済み",
    failed: "APIに接続できません"
  };
  return (
    <main>
      <section className="hero">
        <p className="eyebrow">LOCAL WORKFLOW</p>
        <h1>Image Finisher</h1>
        <p className="description">生成済み画像の仕上げ工程を、安全にまとめて実行します。</p>
        <div className={`status status--${connection}`} role="status">
          <span aria-hidden="true" />{labels[connection]}
        </div>
      </section>
    </main>
  );
}

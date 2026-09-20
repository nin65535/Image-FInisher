import { useEffect, useState } from "react";

import { fetchHealth, scanFolder, selectFolder, type ScanResult } from "./api";

type ConnectionState = "checking" | "connected" | "failed";

export function App() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

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

  async function chooseInput() {
    setBusy(true);
    setMessage(null);
    try {
      const path = await selectFolder();
      if (path) setScan(await scanFolder(path));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "フォルダを確認できませんでした。");
    } finally {
      setBusy(false);
    }
  }

  const labels: Record<ConnectionState, string> = { checking: "APIを確認中", connected: "API接続済み", failed: "APIに接続できません" };
  return (
    <main>
      <header className="hero">
        <div><p className="eyebrow">LOCAL WORKFLOW</p><h1>Image Finisher</h1><p className="description">生成済み画像の仕上げ工程を、安全にまとめて実行します。</p></div>
        <div className={`status status--${connection}`} role="status"><span aria-hidden="true" />{labels[connection]}</div>
      </header>
      <section className="card">
        <div className="section-heading"><div><p className="step">STEP 01</p><h2>入力フォルダ</h2></div><button type="button" onClick={chooseInput} disabled={busy || connection !== "connected"}>{busy ? "確認中…" : "フォルダを選択"}</button></div>
        {!scan && !message && <p className="empty">入力フォルダ直下のPNGを走査します。原本やフォルダの内容は変更しません。</p>}
        {message && <p className="alert alert--error">{message}</p>}
        {scan && <>
          <dl className="paths"><div><dt>入力</dt><dd>{scan.input_folder}</dd></div><div><dt>完成先</dt><dd>{scan.output_folder}</dd></div></dl>
          <div className="metrics"><article><strong>{scan.target_count}</strong><span>対象PNG</span></article><article><strong>{scan.excluded_count}</strong><span>対象外</span></article><article><strong>{scan.groups.length}</strong><span>グループ</span></article></div>
          {scan.errors.length > 0 && <div className="alert alert--error"><strong>開始できません</strong><ul>{scan.errors.map((error, index) => <li key={`${error.code}-${index}`}>{error.message}{error.path && <small>{error.path}</small>}</li>)}</ul></div>}
          {scan.errors.length === 0 && scan.target_count === 0 && <div className="alert">対象PNGがありません。</div>}
          {scan.can_start && <div className="alert alert--success">事前検証に成功しました。すべての完成名を確定できます。</div>}
        </>}
      </section>
      {scan && scan.groups.length > 0 && <section className="card">
        <div className="section-heading"><div><p className="step">NAMING PLAN</p><h2>グループと命名プレビュー</h2></div></div>
        <div className="groups">{scan.groups.map((group) => <article className="group" key={group.name}><div className="group-title"><h3>{group.name}</h3><span>{group.count}枚</span></div><table><thead><tr><th>元ファイル</th><th>完成名</th></tr></thead><tbody>{group.examples.map((image) => <tr key={image.source_path}><td>{image.source_name}</td><td>{image.output_name}</td></tr>)}</tbody></table></article>)}</div>
      </section>}
      <button className="start" type="button" disabled={!scan?.can_start}>処理を開始（フェーズ3以降で有効）</button>
    </main>
  );
}

import { useEffect, useState } from "react";

import { cancelJob, clearJobHistory, createPipelineJob, fetchHealth, fetchJobs, fetchMosaicSettings, openOutputFolder, retryFailedImages, scanFolder, selectFolder, type Job, type ScanResult } from "./api";

type ConnectionState = "checking" | "connected" | "failed";

export function App() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [renameEnabled, setRenameEnabled] = useState(true);
  const [upscaleEnabled, setUpscaleEnabled] = useState(true);
  const [mosaicEnabled, setMosaicEnabled] = useState(false);
  const [mosaicStrength, setMosaicStrength] = useState(200);
  const [mosaicMinimum, setMosaicMinimum] = useState(10);

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

  useEffect(() => { fetchJobs().then(setJobs).catch(() => undefined); }, []);
  useEffect(() => { fetchMosaicSettings().then((value) => { setMosaicStrength(value.value); setMosaicMinimum(value.minimum); }).catch(() => undefined); }, []);

  useEffect(() => {
    const active = jobs.filter((job) => job.status === "queued" || job.status === "running" || job.status === "cancel_requested");
    const streams = active.map((job) => {
      const stream = new EventSource(`/api/jobs/${job.id}/events`);
      stream.addEventListener("job", (event) => {
        const updated = JSON.parse((event as MessageEvent<string>).data) as Job;
        setJobs((current) => [updated, ...current.filter((item) => item.id !== updated.id)].sort((a, b) => b.created_at.localeCompare(a.created_at)));
      });
      return stream;
    });
    return () => streams.forEach((stream) => stream.close());
  }, [jobs.map((job) => `${job.id}:${job.status}`).join("|")]);

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

  async function startJob() {
    if (!scan?.can_start) return;
    setBusy(true); setMessage(null);
    try {
      const job = await createPipelineJob(scan.input_folder, {
        rename: renameEnabled, upscale: upscaleEnabled, mosaic: mosaicEnabled
      }, mosaicStrength);
      setJobs((current) => [job, ...current]);
    } catch (error) { setMessage(error instanceof Error ? error.message : "ジョブを登録できませんでした。"); }
    finally { setBusy(false); }
  }

  async function clearHistory() {
    try { await clearJobHistory(); setJobs((current) => current.filter((job) => !["completed", "failed", "cancelled"].includes(job.status))); }
    catch (error) { setMessage(error instanceof Error ? error.message : "履歴をクリアできませんでした。"); }
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
      <section className="card">
        <div className="section-heading"><div><p className="step">STEP 02</p><h2>リネーム</h2></div></div>
        <label><input type="checkbox" checked={renameEnabled} onChange={(event) => setRenameEnabled(event.target.checked)} /> リネームを有効にする</label>
        <p className="empty">グループごとに元ファイル名順で4桁連番へ整理します。</p>
      </section>
      <section className="card">
        <div className="section-heading"><div><p className="step">STEP 03</p><h2>拡大</h2></div></div>
        <label><input type="checkbox" checked={upscaleEnabled} onChange={(event) => setUpscaleEnabled(event.target.checked)} /> 拡大を有効にする</label>
        <p className="empty">RealESRGAN_x4plus_anime_6Bで4倍拡大後、Lanczos 50%縮小。完成は元寸法の縦横各2倍です。</p>
      </section>
      <section className="card">
        <div className="section-heading"><div><p className="step">STEP 04</p><h2>モザイク</h2></div></div>
        <label><input type="checkbox" checked={mosaicEnabled} onChange={(event) => setMosaicEnabled(event.target.checked)} /> AutoMosaicを有効にする</label>
        <label>モザイク強度 <input type="number" min={mosaicMinimum} step={1} value={mosaicStrength} disabled={!mosaicEnabled} onChange={(event) => setMosaicStrength(Number(event.target.value))} /></label>
        <p className="empty">処理後はBandiViewでモザイク範囲と品質を目視検品してください。</p>
      </section>
      <button className="start" type="button" disabled={!scan?.can_start || busy || !(renameEnabled || upscaleEnabled || mosaicEnabled) || (mosaicEnabled && (!Number.isInteger(mosaicStrength) || mosaicStrength < mosaicMinimum))} onClick={startJob}>{[renameEnabled && "リネーム", upscaleEnabled && "拡大", mosaicEnabled && "モザイク"].filter(Boolean).join("＋") || "工程未選択"}を開始</button>
      <section className="card">
        <div className="section-heading"><div><p className="step">JOB HISTORY</p><h2>ジョブと進捗</h2></div><button type="button" className="secondary" onClick={clearHistory} disabled={!jobs.some((job) => ["completed", "failed", "cancelled"].includes(job.status))}>完了履歴をクリア</button></div>
        {jobs.length === 0 ? <p className="empty">保存されたジョブはありません。</p> : <div className="jobs">{jobs.map((job) => <article className="job" key={job.id}>
          <div className="group-title"><div><strong>{statusLabels[job.status]}</strong><small>{new Date(job.created_at).toLocaleString("ja-JP")} · {job.id.slice(0, 8)}</small></div><span>{job.processed_count} / {job.total_count}枚</span></div>
          <progress value={job.processed_count} max={job.total_count || 1} />
          <p>{job.input_folder}</p>
          <div className="job-counts"><span>成功 {job.counts.completed ?? 0}</span><span>失敗 {job.counts.failed ?? 0}</span><span>キャンセル {job.counts.cancelled ?? 0}</span></div>
          {(job.status === "queued" || job.status === "running") && <button type="button" className="danger" onClick={() => cancelJob(job.id).then((updated) => setJobs((current) => current.map((item) => item.id === updated.id ? updated : item)))}>キャンセル要求</button>}
          {job.status === "failed" && job.images.some((image) => image.status === "failed") && <button type="button" className="secondary" onClick={() => retryFailedImages(job.id).then((updated) => setJobs((current) => current.map((item) => item.id === updated.id ? updated : item))).catch((error: unknown) => setMessage(error instanceof Error ? error.message : "再実行できませんでした。"))}>失敗画像だけ再実行</button>}
          {job.counts.completed > 0 && <button type="button" className="secondary action-button" onClick={() => openOutputFolder(job.id).catch((error: unknown) => setMessage(error instanceof Error ? error.message : "完成フォルダを開けませんでした。"))}>完成フォルダを開く</button>}
          {job.error && <p className="job-error">{job.error}</p>}
          <details><summary>画像の詳細</summary><table><thead><tr><th>元画像</th><th>完成名</th><th>状態</th><th>工程</th></tr></thead><tbody>{job.images.map((image) => <tr key={image.id}><td>{image.source_name}</td><td>{image.output_name}</td><td>{statusLabels[image.status]}</td><td>{image.steps.map((step) => `${step.name}: ${statusLabels[step.status]}`).join(" / ")}{image.error && <small className="step-error">{image.error}</small>}</td></tr>)}</tbody></table></details>
        </article>)}</div>}
      </section>
    </main>
  );
}

const statusLabels = { queued: "待機中", running: "実行中", completed: "完了", failed: "失敗", cancel_requested: "キャンセル要求中", cancelled: "キャンセル" } as const;

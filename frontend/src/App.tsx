import React, { useMemo, useRef, useState } from "react";

// Tailwind-based, polished single-file UI
// - Drag & drop / click upload → POST /api/extract
// - Clean cards, chips, table, tabs, skeleton loader
// - No external component libs

// ---- Types (align with FastAPI) ----

type Quantity = { amount?: number | null; unit?: string | null };

type AllergenItem = {
  name: string;
  present: boolean;
  source?: string | null;
  contains_or_may_contain?: "contains" | "may_contain" | null;
};

type Nutrition = {
  basis?: "per_100g" | "per_serving" | null;
  energy_kj?: number | null;
  energy_kcal?: number | null;
  fat_g?: number | null;
  saturated_fat_g?: number | null;
  carbohydrate_g?: number | null;
  sugars_g?: number | null;
  protein_g?: number | null;
  fiber_g?: number | null;
  salt_g?: number | null;
  sodium_g?: number | null;
  serving_size?: Quantity | null;
};

type ExtractResponse = {
  product_name?: string | null;
  brand?: string | null;
  net_quantity?: Quantity | null;
  ingredients_text?: string | null;
  allergens?: AllergenItem[];
  nutrition?: Nutrition | null;
  warnings?: string[];
  notes?: string | null;
  meta?: Record<string, any>;
};

type ChipProps = React.PropsWithChildren<{
  tone?: "ok" | "warn" | "muted";
}>;

function Chip({ children, tone = "muted" }: ChipProps) {
  const base =
    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold";
  const cls =
    tone === "ok"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : tone === "warn"
      ? "border-orange-200 bg-orange-50 text-orange-800"
      : "border-slate-200 bg-slate-100 text-slate-600 opacity-80"; // ⬅ halkabb
  return <span className={`${base} ${cls}`}>{children}</span>;
}

function Row({ label, value }: { label: string; value?: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-3 text-sm">
      <div className="text-slate-600">{label}</div>
      <div className="font-semibold">{value ?? "—"}</div>
    </div>
  );
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [active, setActive] = useState(false);
  const [data, setData] = useState<ExtractResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"structured" | "json">("structured");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const nutritionRows = useMemo(() => {
    const n = data?.nutrition;
    if (!n) return [] as Array<[string, string]>;
    const pairs: Array<[string, string | number | null | undefined]> = [
      ["Alap", n.basis === "per_100g" ? "100 g" : n.basis === "per_serving" ? "Adagonként" : "—"],
      ["Energia (kJ)", n.energy_kj],
      ["Energia (kcal)", n.energy_kcal],
      ["Zsír (g)", n.fat_g],
      ["•  Telített (g)", n.saturated_fat_g],
      ["Szénhidrát (g)", n.carbohydrate_g],
      ["•  Cukrok (g)", n.sugars_g],
      ["Fehérje (g)", n.protein_g],
      ["Rost (g)", n.fiber_g],
      ["Só (g)", n.salt_g],
      ["Nátrium (g)", n.sodium_g]
    ];
    return pairs
      .filter(([, v]) => v !== undefined && v !== null && !(typeof v === "string" && v.trim() === ""))
      .map(([k, v]) => [k, String(v)] as [string, string]);
  }, [data]);

  const toneFor = (a: AllergenItem): "ok" | "warn" | "muted" => {
    if (!a.present) return "muted"; // ha nincs jelen → szürke
    if (a.contains_or_may_contain === "may_contain") return "warn"; // nyomokban → narancs
    return "ok"; // biztosan tartalmaz → zöld
  };

  const labelFor = (a: AllergenItem) => {
    const suffix =
      a.present && a.contains_or_may_contain === "may_contain" ? " (nyomokban)" : "";
    const src = a.source ? ` • ${a.source}` : "";
    return `${a.name}${suffix}${src}`;
  };

  const onDrop: React.DragEventHandler<HTMLDivElement> = (e) => {
    e.preventDefault();
    setActive(false);
    const f = e.dataTransfer.files?.[0];
    if (f && f.type === "application/pdf") {
      setFile(f);
      setData(null);
      setError(null);
    } else if (f) {
      setError("Kérlek, PDF fájlt dobj be.");
    }
  };

  const onUpload = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("http://localhost:8000/api/extract", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const json = (await res.json()) as ExtractResponse;
      setData(json);
      setTab("structured");
    } catch (e: any) {
      setError(e.message || "Hiba a feldolgozás során.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-indigo-50 text-slate-900">
      <div className="mx-auto max-w-6xl px-4 py-8">
        {/* Header */}
        <div className="mb-4 flex items-center gap-4 rounded-xl bg-slate-900 p-4 text-slate-100 shadow-xl">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-gradient-to-br from-indigo-300 to-indigo-600 font-extrabold text-white shadow-indigo-500/40 shadow-lg">
            PDF
          </div>
          <div className="flex-1">
            <h1 className="text-xl font-sans align-center font-bold text-indigo-600">NUTRIEXT</h1>
            <p className="m-0 text-sm text-slate-300">Allergén & Tápérték kinyerő</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-900 hover:bg-slate-50"
              onClick={() => inputRef.current?.click()}
            >
              Fájl kiválasztása
            </button>
            <button
              className="inline-flex items-center gap-2 rounded-lg border border-indigo-600 bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-md hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={onUpload}
              disabled={!file || loading}
            >
              {loading ? "Feldolgozás…" : "Feltöltés & kinyerés"}
            </button>
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf"
              hidden
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
        </div>

        {/* Grid */}
        <div className={`grid gap-4 ${data ? "md:grid-cols-2" : "grid-cols-1"}`}>
          {/* Upload card */}
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
            <div
              className={`grid place-items-center rounded-lg border-2 border-dashed p-6 text-center transition ${
                active ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-slate-50"
              } ${file ? "py-4" : "py-10"}`}
              onDragOver={(e) => e.preventDefault()}
              onDragEnter={(e) => {
                e.preventDefault();
                setActive(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                setActive(false);
              }}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              role="button"
            >
              <div className="font-semibold">Húzd ide a PDF-et</div>
              <div className="text-sm text-slate-600">…vagy kattints a kiválasztáshoz</div>
              {file && (
                <div className="mt-2 text-sm text-slate-700">
                  Kiválasztva: <span className="font-semibold">{file.name}</span>
                </div>
              )}
            </div>

            {error && (
              <div className="mt-3">
                <Chip tone="warn">⚠️ {error}</Chip>
              </div>
            )}

            {loading && (
              <div className="mt-3 grid gap-2">
                <div className="h-2 rounded bg-slate-200 animate-pulse" />
                <div className="h-2 rounded bg-slate-200 animate-pulse [animation-delay:.15s]" />
                <div className="h-2 rounded bg-slate-200 animate-pulse [animation-delay:.3s]" />
              </div>
            )}
          </div>

          {/* Result card */}
          {data && (
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
              <div className="mb-3 flex gap-2">
                <button
                  className={`rounded-lg px-3 py-2 text-sm font-semibold ${
                    tab === "structured"
                      ? "border border-indigo-600 bg-indigo-600 text-white shadow"
                      : "border border-slate-200 bg-white text-slate-900"
                  }`}
                  onClick={() => setTab("structured")}
                >
                  Strukturált
                </button>
                <button
                  className={`rounded-lg px-3 py-2 text-sm font-semibold ${
                    tab === "json"
                      ? "border border-indigo-600 bg-indigo-600 text-white shadow"
                      : "border border-slate-200 bg-white text-slate-900"
                  }`}
                  onClick={() => setTab("json")}
                >
                  JSON
                </button>
              </div>

              {tab === "json" ? (
                <pre className="max-h-[420px] overflow-auto rounded-lg bg-slate-900 p-3 text-slate-200">
                  {JSON.stringify(data, null, 2)}
                </pre>
              ) : (
                <div className="grid gap-3">
                  {/* Summary */}
                  <div className="rounded-lg border border-slate-200 p-3">
                    <Row label="Terméknév" value={data.product_name ?? "—"} />
                    <div className="h-2" />
                    <Row label="Márka" value={data.brand ?? "—"} />
                    <div className="h-2" />
                    <Row
                      label="Nettó mennyiség"
                      value={
                        data.net_quantity?.amount
                          ? `${data.net_quantity.amount} ${data.net_quantity.unit ?? "g"}`
                          : "—"
                      }
                    />
                  </div>

                  {/* Ingredients */}
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="mb-1 font-bold">Összetevők</div>
                    <div className="whitespace-pre-wrap leading-relaxed">
                      {data.ingredients_text || <span className="text-slate-500">—</span>}
                    </div>
                  </div>

                  {/* Allergens */}
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="mb-1 flex items-center justify-between">
                      <div className="font-bold">Allergének</div>
                      <Chip tone="muted">EU 1169/2011</Chip>
                    </div>
                    {data.allergens && data.allergens.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {data.allergens.map((a, i) => (
                          <Chip key={i} tone={toneFor(a)}>
                            {labelFor(a)}
                          </Chip>
                        ))}
                      </div>
                    ) : (
                      <div className="text-slate-500">Nincs jelölt allergén.</div>
                    )}
                  </div>

                  {/* Nutrition */}
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="mb-1 flex items-center justify-between">
                      <div className="font-bold">Tápérték</div>
                      {data.nutrition?.basis && (
                        <Chip tone="muted">
                          {data.nutrition.basis === "per_100g" ? "100 g" : "Adagonként"}
                        </Chip>
                      )}
                    </div>

                    {nutritionRows.length > 0 ? (
                      <div className="max-h-96 overflow-auto">
                        <table className="w-full border-separate border-spacing-0">
                          <thead>
                            <tr>
                              <th className="sticky top-0 min-w-[200px] bg-slate-50 p-2 text-left text-xs font-semibold text-slate-600">Tápanyag</th>
                              <th className="sticky top-0 min-w-[140px] bg-slate-50 p-2 text-left text-xs font-semibold text-slate-600">Érték</th>
                            </tr>
                          </thead>
                          <tbody>
                            {nutritionRows.map(([k, v], idx) => (
                              <tr key={idx} className="text-sm">
                                <td className="border-b border-slate-200 p-2">{k}</td>
                                <td className="border-b border-slate-200 p-2">{v}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="text-slate-500">Nincsenek tápérték adatok.</div>
                    )}
                  </div>

                  {/* Warnings */}
                  {data.warnings && data.warnings.length > 0 && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
                      <strong>Figyelmeztetések</strong>
                      <ul className="ml-5 mt-1 list-disc text-sm">
                        {data.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mt-4 text-center text-xs text-slate-500">
          nutriext • klkkristof 
        </div>
      </div>
    </div>
  );
}

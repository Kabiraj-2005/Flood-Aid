/*
 * The outbox. This file is the project.
 *
 * Rule: saving a report NEVER touches the network. It writes to IndexedDB
 * and returns. Sending happens later, on its own, whenever a network exists.
 *
 * Three things make it safe:
 *   1. The id is made here, on the phone, before saving. So a retry that the
 *      server already received is recognised and ignored — no duplicates.
 *   2. Nothing leaves the queue until the server confirms it.
 *   3. Text is sent before photos. A 4 MB photo on a weak link must never
 *      block the text a dispatcher needs.
 */

const DB_NAME = "floodaid";
const DB_VERSION = 1;
const STORE_REPORTS = "outbox_reports";
const STORE_PHOTOS = "outbox_photos";
const STORE_SERVER = "server_state";   // reports pulled down + cursor
const STORE_META = "meta";

let _db = null;

function openDB() {
  if (_db) return Promise.resolve(_db);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_REPORTS))
        db.createObjectStore(STORE_REPORTS, { keyPath: "id" });
      if (!db.objectStoreNames.contains(STORE_PHOTOS))
        db.createObjectStore(STORE_PHOTOS, { keyPath: "id" });
      if (!db.objectStoreNames.contains(STORE_SERVER))
        db.createObjectStore(STORE_SERVER, { keyPath: "id" });
      if (!db.objectStoreNames.contains(STORE_META))
        db.createObjectStore(STORE_META, { keyPath: "key" });
    };
    req.onsuccess = () => { _db = req.result; resolve(_db); };
    req.onerror = () => reject(req.error);
  });
}

function tx(store, mode, fn) {
  return openDB().then(db => new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const s = t.objectStore(store);
    const out = fn(s);
    t.oncomplete = () => resolve(out && out.result !== undefined ? out.result : out);
    t.onerror = () => reject(t.error);
  }));
}

/* ---------------------------------------------------------- identity */

// A random id, made here. This is what makes retries safe.
function newId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return "r-" + Date.now() + "-" + Math.random().toString(16).slice(2, 10);
}

async function deviceId() {
  const row = await tx(STORE_META, "readonly", s => s.get("device_id"));
  if (row && row.value) return row.value;
  const id = "d-" + Math.random().toString(16).slice(2, 10);
  await tx(STORE_META, "readwrite", s => s.put({ key: "device_id", value: id }));
  return id;
}

async function getCursor() {
  const row = await tx(STORE_META, "readonly", s => s.get("cursor"));
  return (row && row.value) || 0;
}

async function setCursor(v) {
  return tx(STORE_META, "readwrite", s => s.put({ key: "cursor", value: v }));
}

/* ------------------------------------------------------------ saving */

/**
 * Save a report. Does not touch the network. Never throws on being offline.
 */
export async function saveReport(fields, photos = []) {
  const id = newId();
  const record = {
    id,
    device_id: await deviceId(),
    counter: 1,
    phone_time: Date.now(),
    source: fields.source || "volunteer",
    text: fields.text || "",
    photo_ids: [],
    lat: fields.lat ?? null,
    lon: fields.lon ?? null,
    polygon: fields.polygon ?? null,
    location_confidence: fields.location_confidence ?? 1.0,
    people_count: fields.people_count ?? null,
    injured: fields.injured ? 1 : 0,
    children_elderly: fields.children_elderly ? 1 : 0,
    water_level: fields.water_level ?? null,
    rising: fields.rising ? 1 : 0,
    road_passable: fields.road_passable || "unknown",
    _state: "pending",
    _attempts: 0,
  };

  // Photos go in a SEPARATE queue, drained after all text is through.
  for (const blob of photos) {
    const pid = newId();
    record.photo_ids.push(pid);
    await tx(STORE_PHOTOS, "readwrite", s =>
      s.put({ id: pid, report_id: id, blob, _state: "pending", _attempts: 0 })
    );
  }

  await tx(STORE_REPORTS, "readwrite", s => s.put(record));
  trySync();                       // fire and forget; fails silently offline
  return id;
}

/**
 * Edit an existing queued report. counter goes up so the server knows this
 * is newer than what it has.
 */
export async function editReport(id, patch) {
  const existing = await tx(STORE_REPORTS, "readonly", s => s.get(id));
  if (!existing) return null;
  const updated = {
    ...existing, ...patch,
    counter: (existing.counter || 1) + 1,
    phone_time: Date.now(),
    _state: "pending",
  };
  await tx(STORE_REPORTS, "readwrite", s => s.put(updated));
  trySync();
  return updated;
}

/* ----------------------------------------------------------- reading */

export async function pendingReports() {
  const all = await tx(STORE_REPORTS, "readonly", s => s.getAll());
  return (all || []).filter(r => r._state === "pending");
}

export async function pendingPhotos() {
  const all = await tx(STORE_PHOTOS, "readonly", s => s.getAll());
  return (all || []).filter(p => p._state === "pending");
}

export async function serverReports() {
  return (await tx(STORE_SERVER, "readonly", s => s.getAll())) || [];
}

export async function queueSummary() {
  const [r, p] = await Promise.all([pendingReports(), pendingPhotos()]);
  return { reports: r.length, photos: p.length, items: r };
}

/* -------------------------------------------------------------- sync */

let syncing = false;

export async function trySync(apiBase = "") {
  if (syncing) return { skipped: true };
  if (!navigator.onLine) return { offline: true };
  syncing = true;

  try {
    const reports = await pendingReports();
    const cursor = await getCursor();

    // strip local-only fields before sending
    const payload = reports.map(({ _state, _attempts, ...clean }) => clean);

    const res = await fetch(apiBase + "/api/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reports: payload, last_cursor: cursor }),
    });
    if (!res.ok) throw new Error("server " + res.status);
    const data = await res.json();

    // Only now is it safe to mark them sent.
    for (const r of reports) {
      await tx(STORE_REPORTS, "readwrite", s =>
        s.put({ ...r, _state: "sent" })
      );
    }

    // Store what came back so the map works offline next time.
    for (const c of data.changes || []) {
      await tx(STORE_SERVER, "readwrite", s => s.put(c));
    }
    if (data.cursor) await setCursor(data.cursor);

    syncing = false;
    await drainPhotos(apiBase);       // text first, photos after
    window.dispatchEvent(new CustomEvent("floodaid:synced", { detail: data }));
    return data;

  } catch (err) {
    // Offline or server down. Leave everything in the queue and try later.
    for (const r of await pendingReports()) {
      await tx(STORE_REPORTS, "readwrite", s =>
        s.put({ ...r, _attempts: (r._attempts || 0) + 1 })
      );
    }
    syncing = false;
    return { error: String(err) };
  }
}

async function drainPhotos(apiBase = "") {
  for (const photo of await pendingPhotos()) {
    try {
      const form = new FormData();
      form.append("photo_id", photo.id);
      form.append("report_id", photo.report_id);
      form.append("file", photo.blob);
      const res = await fetch(apiBase + "/api/photos", { method: "POST", body: form });
      if (!res.ok) throw new Error("photo " + res.status);
      await tx(STORE_PHOTOS, "readwrite", s => s.put({ ...photo, _state: "sent" }));
    } catch (e) {
      break;   // connection died again — stop, keep the rest queued
    }
  }
}

/* Retry whenever the network comes back, and periodically. */
window.addEventListener("online", () => trySync());
setInterval(() => { if (navigator.onLine) trySync(); }, 30000);

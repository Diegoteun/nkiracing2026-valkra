/**
 * POST /api/upload
 * Body: { password: string, data: object }
 * Commits data/valkra-nk-prequal.json on GitHub when the password matches.
 */
const crypto = require("crypto");

const REPO = process.env.GITHUB_REPO || "Diegoteun/nkiracing2026-valkra";
const BRANCH = process.env.GITHUB_BRANCH || "main";
const PATH = process.env.GITHUB_PATH || "data/valkra-nk-prequal.json";

function problems(D) {
  const p = [];
  if (!D || typeof D !== "object") return ["geen JSON-object"];
  if (!D.meta || !D.meta.generated_at) p.push("meta.generated_at");
  if (!D.meta || !D.meta.model) p.push("meta.model");
  if (!D.forecast || !D.forecast.split1_cutoff || !D.forecast.split2_cutoff) p.push("forecast");
  if (!D.position_curve || !Array.isArray(D.position_curve.times) || D.position_curve.times.length < 2) p.push("position_curve");
  if (!Array.isArray(D.drivers) || !D.drivers.length) p.push("drivers");
  if (!Array.isArray(D.irating_bands)) p.push("irating_bands");
  if (!Array.isArray(D.irating_histogram)) p.push("irating_histogram");
  if (!D.irating_density || !Array.isArray(D.irating_density.irating)) p.push("irating_density");
  if (!D.irating_summary) p.push("irating_summary");
  return p;
}

function passwordOk(given) {
  const expected = process.env.UPLOAD_PASSWORD || "";
  if (!expected || typeof given !== "string") return false;
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function json(res, status, body) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

async function github(method, urlPath, body) {
  const token = process.env.GITHUB_TOKEN;
  if (!token) throw new Error("GITHUB_TOKEN ontbreekt");
  const res = await fetch(`https://api.github.com/repos/${REPO}/contents/${urlPath}`, {
    method,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      "User-Agent": "valkra-prequal-upload",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = { message: text }; }
  if (!res.ok) {
    const msg = (data && data.message) || `GitHub HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

module.exports = async function handler(req, res) {
  if (req.method === "OPTIONS") {
    res.statusCode = 204;
    res.end();
    return;
  }
  if (req.method !== "POST") {
    return json(res, 405, { ok: false, error: "Alleen POST." });
  }

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch (_) {
      return json(res, 400, { ok: false, error: "Ongeldige JSON-body." });
    }
  }
  if (!body || typeof body !== "object") {
    return json(res, 400, { ok: false, error: "Body verwacht: { password, data }." });
  }

  if (!passwordOk(body.password)) {
    return json(res, 401, { ok: false, error: "Onjuist wachtwoord." });
  }

  const missing = problems(body.data);
  if (missing.length) {
    return json(res, 400, { ok: false, error: `JSON mist: ${missing.join(", ")}.` });
  }

  const content = Buffer.from(JSON.stringify(body.data, null, 1), "utf8").toString("base64");
  const when = body.data.meta.generated_at;
  const message = `Update prequal data (upload ${when})`;

  try {
    let sha;
    try {
      const existing = await github("GET", `${PATH}?ref=${encodeURIComponent(BRANCH)}`);
      sha = existing.sha;
    } catch (err) {
      if (err.status !== 404) throw err;
    }

    await github("PUT", PATH, {
      message,
      content,
      branch: BRANCH,
      sha,
    });

    return json(res, 200, { ok: true, generated_at: when });
  } catch (err) {
    return json(res, 502, { ok: false, error: `Opslaan mislukt: ${err.message}` });
  }
};

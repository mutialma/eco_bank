/* ============================================================
   api.js — HTTP Client & Token Management
   ============================================================ */
'use strict';

// Auto-detect API base URL: same origin in production, localhost in dev
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:5000/api'
  : window.location.origin + '/api';

const Api = {
  token: localStorage.getItem('ecobank_token') || null,

  setToken(t) {
    this.token = t;
    t ? localStorage.setItem('ecobank_token', t) : localStorage.removeItem('ecobank_token');
  },

  headers() {
    const h = { 'Content-Type': 'application/json' };
    if (this.token) h['Authorization'] = 'Bearer ' + this.token;
    return h;
  },

  async request(method, path, body = null) {
    const opts = { method, headers: this.headers() };
    if (body) opts.body = JSON.stringify(body);
    try {
      const res  = await fetch(API_BASE + path, opts);
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || 'Request gagal');
      return data;
    } catch (e) {
      if (e.message === 'Failed to fetch')
        throw new Error('Tidak dapat terhubung ke server. Jalankan: python server.py');
      throw e;
    }
  },

  get(p)    { return this.request('GET',    p);    },
  post(p,b) { return this.request('POST',   p, b); },
  put(p,b)  { return this.request('PUT',    p, b); },
  del(p)    { return this.request('DELETE', p);    },
};

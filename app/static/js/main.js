/**
 * Plateforme RH — JavaScript principal
 *
 * Initialisation globale :
 *   - Configuration du token CSRF pour toutes les requêtes AJAX
 *   - Initialisation des tooltips et popovers Bootstrap
 *   - Helpers utilitaires
 */

'use strict';

// ── CSRF pour les requêtes fetch ─────────────────────────────────────────────
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

/**
 * Wrapper fetch avec le header CSRF et JSON par défaut.
 * Usage : await apiFetch('/api/v1/employees', { method: 'POST', body: {...} })
 */
async function apiFetch(url, options = {}) {
  const defaults = {
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken':  csrfToken || '',
    },
  };
  const merged = {
    ...defaults,
    ...options,
    headers: { ...defaults.headers, ...(options.headers || {}) },
  };
  if (merged.body && typeof merged.body === 'object') {
    merged.body = JSON.stringify(merged.body);
  }
  const response = await fetch(url, merged);
  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new Error(err?.error?.message || 'Erreur réseau');
  }
  return response.json();
}

// ── Initialisation Bootstrap ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Tooltips
  document.querySelectorAll('[data-bs-toggle="tooltip"]')
    .forEach(el => new bootstrap.Tooltip(el));

  // Popovers
  document.querySelectorAll('[data-bs-toggle="popover"]')
    .forEach(el => new bootstrap.Popover(el));

  // Auto-dismiss des alertes après 5 secondes
  document.querySelectorAll('.alert.alert-success, .alert.alert-info')
    .forEach(alert => setTimeout(() => {
      bootstrap.Alert.getOrCreateInstance(alert)?.close();
    }, 5000));

  // Afficher / masquer un champ mot de passe (bouton [data-password-toggle="<id-du-champ>"])
  document.querySelectorAll('[data-password-toggle]').forEach(btn => {
    const input = document.getElementById(btn.dataset.passwordToggle);
    const icon  = btn.querySelector('i');
    if (!input || !icon) return;
    btn.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      icon.className = show ? 'bi bi-eye-slash' : 'bi bi-eye';
      btn.setAttribute('aria-label', show ? 'Masquer le mot de passe' : 'Afficher le mot de passe');
    });
  });
});

// ── Utilitaires ──────────────────────────────────────────────────────────────

/** Formate un nombre en euros (affichage côté client). */
function formatEuros(value) {
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(value);
}

/** Formate une date ISO en français. */
function formatDateFr(isoString) {
  if (!isoString) return '—';
  return new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })
    .format(new Date(isoString));
}

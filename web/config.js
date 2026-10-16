// Runtime config. apiBase = '' → static-only mode (submission/voting disabled).
// If the API is unreachable the site falls back to static JSON automatically.
// Override per visit with ?api=https://api.example.com  (useful for local testing).
window.MCBENCH_CONFIG = { apiBase: 'https://mcbench-api.velaios.com' };

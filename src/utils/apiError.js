/**
 * Turn any FastAPI error body into a string safe to render.
 *
 * `detail` is not always a string, and assuming it is crashes the app with
 * "Objects are not valid as a React child". It arrives in three shapes:
 *
 *   1. string  — `raise HTTPException(400, "Job not found")`
 *   2. object  — `raise HTTPException(422, detail={...})`, e.g. the
 *                SUMMARY_DURATION_EXCEEDS_VIDEO payload, which carries a
 *                human-readable `message` alongside machine-readable fields
 *   3. array   — FastAPI's own request-validation errors, a list of
 *                `{loc, msg, type}` objects, returned by ANY endpoint when a
 *                field fails validation
 *
 * Shape 2 was what broke the merge page: `setErrorMsg(data.detail || '…')`
 * put the whole object into state and React refused to render it.
 */
export function extractErrorMessage(body, fallback = 'Something went wrong. Please retry.') {
  const detail = body?.detail;

  if (typeof detail === 'string' && detail.trim()) return detail;

  // Structured application error — prefer the message written for humans.
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    if (typeof detail.message === 'string' && detail.message.trim()) return detail.message;
  }

  // FastAPI request-validation errors.
  if (Array.isArray(detail) && detail.length) {
    const parts = detail
      .map((d) => (typeof d === 'string' ? d : d?.msg))
      .filter(Boolean);
    if (parts.length) return parts.join('. ');
  }

  if (typeof body?.message === 'string' && body.message.trim()) return body.message;

  return fallback;
}

/**
 * The structured payload itself, when the server sent one — so a caller can
 * react to `error_code` / `allowed_durations` rather than parse prose.
 * Returns null for plain string or validation-array errors.
 */
export function extractErrorDetail(body) {
  const detail = body?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.error_code) {
    return detail;
  }
  return null;
}

export default extractErrorMessage;

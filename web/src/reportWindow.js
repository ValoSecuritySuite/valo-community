const nativeWindowOpen = window.open.bind(window)

/**
 * Open a same-origin writable window for locally generated reports.
 *
 * Chrome and Edge return null when `noopener` is supplied to window.open,
 * which prevents the caller from writing the generated report document.
 * This helper opens the blank window first, then severs the opener reference
 * after the report content has been written by the caller.
 */
export function openWritableReportWindow() {
  return nativeWindowOpen('', '_blank')
}

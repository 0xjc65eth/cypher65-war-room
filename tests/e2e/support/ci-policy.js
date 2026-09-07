/** Return true only for the explicit CI values supported by the test runner. */
export function isCiEnabled(value = process.env.CI) {
  return /^(1|true)$/i.test(value || '');
}

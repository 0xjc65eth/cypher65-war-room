/**
 * Convert documented TestsStream events to one drained machine receipt.
 * @param {AsyncIterable<object>} source Node's structured reporter event stream.
 * @returns {AsyncGenerator<string>} One JSON receipt after stream completion.
 * @example childReporter(structuredNodeTestEvents)
 */
export default async function* childReporter(source) {
  const tests = [], failures = [], diagnostics = [];
  let rootPlan = null;
  for await (const { type, data } of source) {
    if (type === 'test:plan' && data.nesting === 0) rootPlan = data.count;
    if (type === 'test:fail') failures.push({ name: data.name, message: data.details?.error?.message });
    if (type === 'test:stderr' || type === 'test:stdout') diagnostics.push(data.message);
    if (type !== 'test:pass' && type !== 'test:fail') continue;
    // Node wraps an empty/early-exiting file as a synthetic passing test at 1:1.
    // That wrapper is not proof that a declared test callback ran (including v20).
    const wrapper = data.name === data.file && data.line === 1 && data.column === 1;
    if (wrapper || data.details?.type === 'suite') continue;
    tests.push({ file: data.file, name: data.name, outcome: type === 'test:pass' ? 'pass' : 'fail',
      skipped: !!data.skip, todo: !!data.todo,
      error: type === 'test:fail' ? { message: data.details?.error?.message } : null });
  }
  // Emitted only after the event stream drains, not on a human-readable TAP line.
  yield JSON.stringify({ protocol: 'cypher65-node-child-v1', completed: rootPlan !== null,
    rootPlan, tests, executed: tests.filter(test => !test.skipped && !test.todo).length,
    failed: failures.length, failures, diagnostics }) + '\n';
}

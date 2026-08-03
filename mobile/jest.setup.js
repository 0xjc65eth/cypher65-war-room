// CYPHER65 Mobile — Jest setup
// Intentionally minimal: the jest-expo preset already mocks expo/react-native
// native modules. (Do NOT add an explicit `NativeAnimatedHelper` mock here —
// that module was removed/renamed in RN 0.74 and the mock path would throw
// "Cannot find module", breaking the CI job.)

// @react-native-async-storage/async-storage ships a native module that is
// null under jest. jest-expo does NOT auto-mock it (the store hooks import it
// at module load), so provide a tiny in-memory mock here.
jest.mock('@react-native-async-storage/async-storage', () => {
  let store = {};
  return {
    __esModule: true,
    default: {
      getItem: jest.fn(async (k) => (k in store ? store[k] : null)),
      setItem: jest.fn(async (k, v) => { store[k] = String(v); }),
      removeItem: jest.fn(async (k) => { delete store[k]; }),
      clear: jest.fn(async () => { store = {}; }),
    },
  };
});

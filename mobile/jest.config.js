// CYPHER65 Mobile — Jest configuration
// Uses the jest-expo preset (matches expo SDK 51) so expo/react-native
// modules are transformed and native modules are mocked automatically.
// External-review quick win: closes the "mobile not tested in CI" gap.
module.exports = {
  preset: "jest-expo",
  testMatch: ["**/tests/**/*.test.[jt]s?(x)"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  transformIgnorePatterns: [
    "node_modules/(?!((jest-)?react-native|jest-expo|@react-native(-community)?|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@sentry/react-native|native-base|react-native-svg|zustand|@tanstack|expo-.*)/)",
  ],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
};

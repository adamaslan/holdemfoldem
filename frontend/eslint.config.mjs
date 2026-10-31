// Hard gate for the eic1 /connections bug class: a hook called after a
// conditional early return is invisible in a diff and fatal at runtime
// (React #310/#418). This config intentionally lints ONLY react-hooks rules;
// it is installed in CI with `npm install --no-save` (see
// .github/workflows/frontend-lint.yml) so package-lock.json stays untouched.
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default [
  {
    files: ["src/**/*.{ts,tsx,js,jsx}"],
    languageOptions: { parser: tseslint.parser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
];

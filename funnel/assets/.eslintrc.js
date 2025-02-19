const OFF = 0;
const WARN = 1;
const ERROR = 2;
module.exports = {
  parser: 'babel-eslint',
  env: {
    browser: true,
    es6: true,
    jquery: true,
  },
  extends: [
    'airbnb-base',
    'plugin:prettier/recommended',
    'plugin:cypress/recommended',
  ],
  rules: {
    'no-console': WARN,
    'prefer-arrow-callback': [ERROR, { allowNamedFunctions: true }],
    'prefer-const': WARN,
    'new-cap': WARN,
    'no-param-reassign': [ERROR, { props: false }],
    // allow debugger during development
    'no-debugger': process.env.NODE_ENV === 'production' ? ERROR : OFF,
  },
};

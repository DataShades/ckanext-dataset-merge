/**
 * Configuration for gulp tasks
 */
const { resolve } = require("path");
const { src, dest, watch, parallel } = require("gulp");

const if_ = require("gulp-if");
const sourcemaps = require("gulp-sourcemaps");
const sass = require("gulp-sass")(require("sass"));
const postcss = require("gulp-postcss");
const combineQueries = require("postcss-sort-media-queries");
const touch = require("gulp-touch-fd");
const cleanCSS = require("gulp-clean-css");

// helper that used to modify behavior of pipes and produce extra debug details
// when DEBUG envvar is present.
const isDev = () => !!process.env.DEBUG;

// SASS themes to compile. Each lives in its own extension's assets directory
// with a `<entry>` file under `scss/` and compiled output written to `styles/`.
const themes = [
  { name: "dataset_merge", entry: "merge.scss" },
];

const assetsDir = (name) =>
  resolve(__dirname, "ckanext", name, "assets");

/**
 * Compile one theme's SASS sources into a CSS bundle.
 */
const buildTheme = (theme) => {
  const srcDir = resolve(assetsDir(theme.name), "scss");
  const destDir = resolve(assetsDir(theme.name), "styles");

  const task = () =>
    src(resolve(srcDir, theme.entry))
      // keep details about original SASS code
      .pipe(if_(isDev, sourcemaps.init()))

      // compile SASS into CSS. includePaths directive enables import from
      // node_modules packages
      .pipe(
        sass({
          includePaths: ["node_modules"],
          // silenceDeprecations: ["import", "legacy-js-api"],
        }).on("error", sass.logError),
      )

      // group identical @media queries into single block and sort them using
      // mobile-first order
      .pipe(postcss([combineQueries]))

      // add source maps if DEBUG enabled. Minify and optimize CSS otherwise
      .pipe(
        if_(
          isDev,
          sourcemaps.write(),
          cleanCSS({
            level: 2,
            format: {
              breaks: {
                afterProperty: true,
                afterRuleBegins: true,
              },
            },
          }),
        ),
      )

      // write output to destination folder
      .pipe(dest(destDir))

      // update modification date of CSS to force re-building WebAssets by CKAN
      .pipe(touch());

  task.displayName = `build:${theme.name}`;
  return task;
};

const build = parallel(...themes.map(buildTheme));

/**
 * Recompile every theme immediately and after any change of SCSS files inside
 * the source directories.
 */
const watchStyles = () =>
  watch(
    themes.map((theme) =>
      resolve(assetsDir(theme.name), "scss", "**/*.scss"),
    ),
    { ignoreInitial: false },
    build,
  );

exports.watch = watchStyles;
exports.build = build;

'use strict';

exports.ada = { LINE_REGEX: /^--.*/ };
exports.apl = { LINE_REGEX: /^⍝.*/ };

exports.applescript = {
  BLOCK_OPEN_REGEX: /^\(\*/,
  BLOCK_CLOSE_REGEX: /^\*\)/
};

exports.csharp = {
  LINE_REGEX: /^\/\/.*/
};

exports.haskell = {
  BLOCK_OPEN_REGEX: /^\{-/,
  BLOCK_CLOSE_REGEX: /^-\}/,
  LINE_REGEX: /^--.*/
};

exports.html = {
  BLOCK_OPEN_REGEX: /^\n*<!--(?!-?>)/,
  BLOCK_CLOSE_REGEX: /^(?<!(?:<!-))-->/,
  BLOCK_CLOSE_LOOSE_REGEX: /^(?<!(?:<!-))--\s*>/,
  BLOCK_CLOSE_STRICT_NEWLINE_REGEX: /^(?<!(?:<!-))-->(\s*\n+|\n*)/,
  BLOCK_CLOSE_STRICT_LOOSE_REGEX: /^(?<!(?:<!-))--\s*>(\s*\n+|\n*)/
};

exports.javascript = {
  BLOCK_OPEN_REGEX: /^\/\*\*?(!?)/,
  BLOCK_CLOSE_REGEX: /^\*\/(\n?)/,
  LINE_REGEX: /^\/\/(!?).*/
};

exports.lua = {
  BLOCK_OPEN_REGEX: /^--\[\[/,
  BLOCK_CLOSE_REGEX: /^\]\]/,
  LINE_REGEX: /^--.*/
};

exports.matlab = {
  BLOCK_OPEN_REGEX: /^%{/,
  BLOCK_CLOSE_REGEX: /^%}/,
  LINE_REGEX: /^%.*/
};

exports.perl = {
  LINE_REGEX: /^#.*/
};

exports.php = {
  ...exports.javascript,
  LINE_REGEX: /^(#|\/\/).*?(?=\?>|\n)/
};

exports.python = {
  BLOCK_OPEN_REGEX: /^"""/,
  BLOCK_CLOSE_REGEX: /^"""/,
  LINE_REGEX: /^#.*/
};

exports.ruby = {
  BLOCK_OPEN_REGEX: /^=begin/,
  BLOCK_CLOSE_REGEX: /^=end/,
  LINE_REGEX: /^#.*/
};

exports.shebang = exports.hashbang = {
  LINE_REGEX: /^#!.*/
};

exports.c = exports.javascript;
exports.csharp = exports.javascript;
exports.css = exports.javascript;
exports.java = exports.javascript;
exports.js = exports.javascript;
exports.less = exports.javascript;
exports.pascal = exports.applescript;
exports.ocaml = exports.applescript;
exports.sass = exports.javascript;
exports.sql = exports.ada;
exports.swift = exports.javascript;
exports.ts = exports.javascript;
exports.typscript = exports.javascript;
exports.xml = exports.html;

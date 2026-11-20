/// <reference types="node" />
/**
 * The Cameras column header sat left while its numbers sat right: the
 * numeric rule lost to `.models-tab__table th { text-align: left }` on
 * specificity. The numeric rule must be at least as specific.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// Read from disk: vitest stubs CSS imports (even ?raw) to an empty string.
const css = readFileSync(new URL('../SettingsModelsTab.css', import.meta.url), 'utf8');

describe('AI Models tables: numeric columns', () => {
  it('right-aligns header and cells with a rule that beats the th default', () => {
    expect(css).toMatch(/\.models-tab__table th\s*\{[^}]*text-align:\s*left/);
    expect(css).toMatch(/\.models-tab__table \.models-tab__num\s*\{[^}]*text-align:\s*right/);
    expect(css).not.toMatch(/(^|\n)\.models-tab__num\s*\{/);
  });
});

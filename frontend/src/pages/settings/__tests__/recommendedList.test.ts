/**
 * AI Models list: recommended uploaded models carry a badge and sort first.
 */
import { describe, expect, it } from 'vitest';
import type { MergedModel } from '../mergeModels';
import { recommendedFirst, recommendedLabels } from '../mergeModels';

function merged(model_id: string, recommended: string[] = [], labels: Record<string, string> = {}): MergedModel {
  return {
    key: model_id, model_id, origin: 'uploaded', displayName: model_id,
    status: { model_id, recommended_for: recommended, violation_type_labels: labels },
  } as unknown as MergedModel;
}

describe('recommended models in the AI Models list', () => {
  it("labels from the server, else humanized", () => {
    expect(recommendedLabels(merged('hard_hat', ['missing_hardhat'], { missing_hardhat: 'Missing hard hat' }))).toEqual(['Missing hard hat']);
    expect(recommendedLabels(merged('x', ['missing_widget']))).toEqual(['Missing widget']);
    expect(recommendedLabels(merged('y'))).toEqual([]);
  });

  it('falls back to the admin record when the model has no status entry', () => {
    const offline = { key: 'v', model_id: 'v', origin: 'uploaded', displayName: 'v',
      store: { recommended_for: ['missing_vest'] } } as unknown as MergedModel;
    expect(recommendedLabels(offline)).toEqual(['Missing vest']);
  });

  it('sorts recommended first, keeping the order otherwise', () => {
    const list = [merged('a'), merged('b', ['missing_vest']), merged('c'), merged('d', ['missing_hardhat'])];
    expect(recommendedFirst(list).map((m) => m.model_id)).toEqual(['b', 'd', 'a', 'c']);
  });
});

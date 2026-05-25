/**
 * Default renderer for completed bookmark-analyses summary blobs
 * whose model_id doesn't have a dedicated visualization yet.
 *
 * Just pretty-prints the JSON. Each model that gets its own renderer
 * peels off into a sibling component (see TankOverflowSummary).
 */

import './RawJsonSummary.css';

interface RawJsonSummaryProps {
  summary: Record<string, unknown> | null;
}

export function RawJsonSummary({ summary }: RawJsonSummaryProps) {
  return (
    <>
      <p className="raw-json-summary__note">
        A dedicated renderer for this model is coming in a later phase.
        Raw summary below:
      </p>
      <pre className="raw-json-summary__pre">
        {JSON.stringify(summary ?? {}, null, 2)}
      </pre>
    </>
  );
}

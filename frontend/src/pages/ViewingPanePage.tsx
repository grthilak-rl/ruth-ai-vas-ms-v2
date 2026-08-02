import { ViewingPane } from '../components/viewing-pane/ViewingPane';

/**
 * Viewing Pane Page (/cameras/viewing-pane)
 *
 * Registered OUTSIDE AppShell so it renders with no nav, header or padding —
 * the wall must show camera feeds and nothing else.
 *
 * It is a real route rather than an overlay so the URL can be bookmarked or
 * set as a kiosk browser's homepage: the display then restores itself after a
 * power cut without anyone walking over to click something.
 */
export function ViewingPanePage() {
  return <ViewingPane />;
}

import { Navigate, useParams } from 'react-router-dom';

/**
 * /admin/models/:modelPk -> /settings/models/:modelPk
 *
 * A component rather than a static redirect because the param has to be
 * carried across; a plain <Navigate to="/settings/models"> would silently
 * drop which model the link pointed at.
 */
export function RedirectModelDetail() {
  const { modelPk = '' } = useParams();
  return <Navigate to={`/settings/models/${modelPk}`} replace />;
}

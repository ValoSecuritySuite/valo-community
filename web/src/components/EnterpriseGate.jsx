import { useOutletContext } from 'react-router-dom'

import EnterpriseUpsell from './EnterpriseUpsell.jsx'

export default function EnterpriseGate({ feature, children }) {
  const { isCommunity } = useOutletContext() || {}

  if (isCommunity) {
    return <EnterpriseUpsell feature={feature} />
  }

  return children
}

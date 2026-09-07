import type { RelationshipLabel } from '../api/types'

// Small colored badge for a relationship label. Colors are flat, no gradients.
const COLORS: Record<RelationshipLabel, string> = {
  consistent: '#166534',
  contradictory: '#991b1b',
  superseded: '#9a3412',
  corrected: '#854d0e',
  extended: '#1e40af',
  cancelled: '#7f1d1d',
  unresolved: '#374151',
}

export default function LabelBadge({ label }: { label: RelationshipLabel }) {
  return (
    <span className="badge" style={{ backgroundColor: COLORS[label] ?? '#374151' }}>
      {label}
    </span>
  )
}

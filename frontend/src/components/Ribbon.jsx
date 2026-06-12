/**
 * Ribbon — Island swallowtail banner title, ported from island shared.jsx <Title>
 * color: 'green' | 'app-teal' | 'app-yellow' | 'app-blue' | 'app-pink' | 'app-orange' | 'app-red' | 'purple' | 'brown'
 */
const RIBBON_COLORS = {
  green:        { rf: '#27d039', rb: '#20992a', rk: '#115017', rt: '#fff' },
  'app-pink':   { rf: '#f8a6b2', rb: '#e06880', rk: '#a03060', rt: '#fff' },
  'app-blue':   { rf: '#889df0', rb: '#5068d8', rk: '#2030a0', rt: '#fff' },
  'app-yellow': { rf: '#f7cd67', rb: '#d4a030', rk: '#8a6010', rt: '#725d42' },
  'app-teal':   { rf: '#82d5bb', rb: '#40a880', rk: '#186048', rt: '#fff' },
  'app-orange': { rf: '#e59266', rb: '#c06a30', rk: '#7a3a10', rt: '#fff' },
  'app-red':    { rf: '#fc736d', rb: '#d43030', rk: '#900010', rt: '#fff' },
  purple:       { rf: '#b77dee', rb: '#9050d0', rk: '#5a1a9a', rt: '#fff' },
  brown:        { rf: '#9a835a', rb: '#705830', rk: '#3a2810', rt: '#fff' },
}

export default function Ribbon({ children, color = 'green', size = 20, style }) {
  const c = RIBBON_COLORS[color] || RIBBON_COLORS.green
  const vars = {
    '--rf': c.rf,
    '--rb': c.rb,
    '--rk': c.rk,
    '--rt': c.rt,
    fontSize: size,
    ...style,
  }
  return (
    <span className="ribbon" style={vars}>
      <i className="rbBack rbBackL" />
      <i className="rbBack rbBackR" />
      <i className="rbFold rbFoldL" />
      <i className="rbFold rbFoldR" />
      <i className="rbFront" />
      <span className="rbText">{children}</span>
    </span>
  )
}

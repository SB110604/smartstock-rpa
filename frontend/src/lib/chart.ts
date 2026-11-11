import { useTheme } from './theme';

/** Validated categorical palette (fixed order, never cycled) + chart chrome, per colour mode. */
const LIGHT = {
  series: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  seq: ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95'],
  status: { good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b' },
  grid: '#e1e0d9',
  axis: '#c3c2b7',
  muted: '#898781',
  ink: '#52514e',
  band: '#cde2fb',
};
const DARK = {
  series: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
  seq: ['#184f95', '#1c5cab', '#256abf', '#3987e5', '#6da7ec', '#9ec5f4'],
  status: LIGHT.status,
  grid: '#2c2c2a',
  axis: '#383835',
  muted: '#898781',
  ink: '#c3c2b7',
  band: '#1c3a5e',
};

export type ChartColors = typeof LIGHT;

export function useChartColors(): ChartColors {
  const [theme] = useTheme();
  return theme === 'dark' ? DARK : LIGHT;
}

/** Shared Recharts chrome: recessive grid/axes, tick text in muted ink. */
export function axisProps(c: ChartColors) {
  return { stroke: c.axis, tick: { fill: c.muted, fontSize: 11 }, tickLine: false };
}

export function tooltipStyle(c: ChartColors) {
  return {
    contentStyle: { background: c === DARK ? '#1a1a19' : '#fcfcfb', border: `1px solid ${c.grid}`, borderRadius: 8, fontSize: 12 },
    labelStyle: { color: c.ink },
  };
}

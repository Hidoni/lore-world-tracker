import {
  BookIcon,
  BoxIcon,
  CalendarClockIcon,
  CalendarIcon,
  CastleIcon,
  CircleIcon,
  CrownIcon,
  FileTextIcon,
  FlagIcon,
  FlameIcon,
  GemIcon,
  GitBranchIcon,
  GlobeIcon,
  HeartIcon,
  HomeIcon,
  ImageIcon,
  LandmarkIcon,
  LanguagesIcon,
  LeafIcon,
  MapIcon,
  MapPinIcon,
  MountainIcon,
  OrbitIcon,
  PawPrintIcon,
  ScrollIcon,
  ShieldIcon,
  ShipIcon,
  SkullIcon,
  SparklesIcon,
  StarIcon,
  SwordIcon,
  TreePineIcon,
  UserIcon,
  UsersIcon,
  type LucideIcon,
} from 'lucide-react'

/**
 * The curated icons kinds may use (frontend.md §11): lucide names as the server registry sends
 * them. Custom kinds pick from this set; unknown names fall back to a circle.
 */
export const iconMap = {
  book: BookIcon,
  box: BoxIcon,
  calendar: CalendarIcon,
  'calendar-clock': CalendarClockIcon,
  castle: CastleIcon,
  circle: CircleIcon,
  crown: CrownIcon,
  'file-text': FileTextIcon,
  flag: FlagIcon,
  flame: FlameIcon,
  gem: GemIcon,
  'git-branch': GitBranchIcon,
  globe: GlobeIcon,
  heart: HeartIcon,
  home: HomeIcon,
  image: ImageIcon,
  landmark: LandmarkIcon,
  languages: LanguagesIcon,
  leaf: LeafIcon,
  map: MapIcon,
  'map-pin': MapPinIcon,
  mountain: MountainIcon,
  orbit: OrbitIcon,
  'paw-print': PawPrintIcon,
  scroll: ScrollIcon,
  shield: ShieldIcon,
  ship: ShipIcon,
  skull: SkullIcon,
  sparkles: SparklesIcon,
  star: StarIcon,
  sword: SwordIcon,
  'tree-pine': TreePineIcon,
  user: UserIcon,
  users: UsersIcon,
} as const satisfies Record<string, LucideIcon>

export type IconName = keyof typeof iconMap

export function isIconName(name: string): name is IconName {
  return Object.hasOwn(iconMap, name)
}

/** The icon for a name, or the fallback circle. */
export function iconFor(name: string): LucideIcon {
  return isIconName(name) ? iconMap[name] : CircleIcon
}

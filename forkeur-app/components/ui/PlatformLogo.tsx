type Props = {
  platform: string
  size?: number
  className?: string
}

const PLATFORM_NAMES: Record<string, string> = {
  uber_eats: 'Uber Eats',
  deliveroo: 'Deliveroo',
  takeaway: 'Takeaway.com',
  direct: 'Direct',
}

function UberEatsLogo({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role="img"
      aria-label="Uber Eats"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Black circle with UE monogram — recognizable at small sizes */}
      <circle cx="12" cy="12" r="11" fill="#000000" />
      <text
        x="12"
        y="16"
        textAnchor="middle"
        fontSize="9"
        fontFamily="Arial, sans-serif"
        fontWeight="bold"
        fill="#06C167"
        letterSpacing="-0.5"
      >
        UE
      </text>
    </svg>
  )
}

function DeliverooLogo({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role="img"
      aria-label="Deliveroo"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Teal rounded square background */}
      <rect x="1" y="1" width="22" height="22" rx="5" fill="#00CCBC" />
      {/* Simplified kangaroo silhouette */}
      {/* Body */}
      <ellipse cx="13" cy="13" rx="4" ry="5" fill="white" />
      {/* Head */}
      <ellipse cx="15.5" cy="8" rx="2.5" ry="2.5" fill="white" />
      {/* Ear */}
      <ellipse cx="16.5" cy="5.5" rx="1" ry="1.5" fill="white" />
      {/* Tail */}
      <path d="M9 15 Q7 16 7.5 18 Q8 19 9 18.5" stroke="white" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      {/* Front paw */}
      <path d="M13 11 Q11 10 10.5 11.5" stroke="white" strokeWidth="1.2" fill="none" strokeLinecap="round" />
      {/* Pouch */}
      <ellipse cx="12.5" cy="14" rx="1.5" ry="1.2" fill="#00CCBC" />
    </svg>
  )
}

function TakeawayLogo({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role="img"
      aria-label="Takeaway.com"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Orange rounded square background */}
      <rect x="1" y="1" width="22" height="22" rx="5" fill="#FF8000" />
      {/* Stylized fork / chopstick mark */}
      {/* Left tine */}
      <path d="M8 5 L8 11 Q8 13 10 13 L10 19" stroke="white" strokeWidth="1.8" fill="none" strokeLinecap="round" />
      {/* Right tine — slight curve inward */}
      <path d="M12 5 L12 11 Q12 13 10 13" stroke="white" strokeWidth="1.8" fill="none" strokeLinecap="round" />
      {/* Handle */}
      <path d="M10 13 L10 19" stroke="white" strokeWidth="1.8" fill="none" strokeLinecap="round" />
      {/* Spoon on the right */}
      <ellipse cx="16" cy="7.5" rx="2" ry="2.5" fill="white" />
      <path d="M16 10 L16 19" stroke="white" strokeWidth="1.8" fill="none" strokeLinecap="round" />
    </svg>
  )
}

export default function PlatformLogo({ platform, size = 18, className }: Props) {
  const fullName = PLATFORM_NAMES[platform] ?? platform

  const logo = (() => {
    switch (platform) {
      case 'uber_eats':
        return <UberEatsLogo size={size} />
      case 'deliveroo':
        return <DeliverooLogo size={size} />
      case 'takeaway':
        return <TakeawayLogo size={size} />
      default:
        return null
    }
  })()

  if (!logo) {
    return (
      <span className={`text-xs text-stone-500 ${className ?? ''}`}>
        {fullName}
      </span>
    )
  }

  return (
    <span
      className={`inline-flex items-center justify-center ${className ?? ''}`}
      title={fullName}
    >
      {logo}
    </span>
  )
}

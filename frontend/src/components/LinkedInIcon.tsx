"use client";

interface LinkedInIconProps {
  className?: string;
}

export function LinkedInIcon({ className = "w-4 h-4" }: LinkedInIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="none"
    >
      <rect width="24" height="24" rx="4" fill="#0A66C2" />
      <path
        d="M7.5 10.1H5.1V18.5H7.5V10.1ZM6.3 5.5C5.5 5.5 4.9 6.1 4.9 6.9C4.9 7.7 5.5 8.3 6.3 8.3C7.1 8.3 7.7 7.7 7.7 6.9C7.7 6.1 7.1 5.5 6.3 5.5ZM18.9 13.4C18.9 10.9 17.5 9.8 15.6 9.8C14.1 9.8 13.3 10.6 13 11.2V10.1H10.7C10.7 10.8 10.7 18.5 10.7 18.5H13.1V13.8C13.1 13.5 13.1 13.2 13.2 13C13.4 12.4 13.9 11.8 14.8 11.8C15.9 11.8 16.5 12.7 16.5 14V18.5H18.9V13.4Z"
        fill="#FFFFFF"
      />
    </svg>
  );
}

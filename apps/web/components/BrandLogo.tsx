import Image from "next/image";

export function BrandLogo({ priority = false }: { priority?: boolean }) {
  return (
    <div className="brand-logo-frame">
      <Image
        className="brand-logo-image"
        src="/drona-logo.png"
        alt="Drona Logitech"
        width={613}
        height={184}
        priority={priority}
      />
    </div>
  );
}

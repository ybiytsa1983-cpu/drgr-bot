interface PreviewFrameProps {
  html: string;
}

export function PreviewFrame({ html }: PreviewFrameProps) {
  return (
    <div className="h-[520px] overflow-hidden rounded-xl border border-slate-700 bg-white">
      <iframe
        title="Editor preview"
        sandbox="allow-scripts allow-forms"
        className="h-full w-full"
        srcDoc={html}
      />
    </div>
  );
}

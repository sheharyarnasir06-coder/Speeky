"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { toast } from "react-toastify";
import { Flag, Info, MessageSquare, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { addPeerComment, listPeerComments, reportComment, type PeerComment } from "@/lib/interviewCoach";

export default function PeerReviewPage() {
  const params = useParams<{ shareId: string }>();
  const [comments, setComments] = React.useState<PeerComment[] | null>(null);
  const [commentText, setCommentText] = React.useState("");
  const [isPosting, setIsPosting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(() => {
    listPeerComments(params.shareId)
      .then(setComments)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load this review."));
  }, [params.shareId]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  async function handlePost() {
    if (!commentText.trim()) return;
    setError(null);
    setIsPosting(true);
    try {
      await addPeerComment(params.shareId, commentText.trim());
      setCommentText("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsPosting(false);
    }
  }

  async function handleReport(commentId: string) {
    try {
      await reportComment(commentId);
      refresh();
      toast.success("Comment reported.");
    } catch {
      toast.error("Couldn't report this comment. Try again.");
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          Peer Review
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Leave feedback on this shared interview session.
        </p>
      </div>

      <div className="flex items-start gap-2.5 rounded-xl border border-info/30 bg-info/10 px-4 py-3 text-sm text-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" aria-hidden="true" />
        The interview transcript itself isn&apos;t viewable here yet — the backend doesn&apos;t
        expose a shared-session detail endpoint, only comments. You can still read and
        leave feedback below.
      </div>

      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground">Comments</h2>
        </div>

        {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

        <div className="mt-4 flex flex-col gap-3">
          {comments === null ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : comments.length === 0 ? (
            <p className="text-sm text-muted-foreground">No comments yet — be the first to leave feedback.</p>
          ) : (
            comments.map((comment) => (
              <div key={comment.comment_id} className="rounded-xl border border-border bg-surface p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm text-foreground">{comment.comment_text}</p>
                  <button
                    type="button"
                    onClick={() => handleReport(comment.comment_id)}
                    aria-label="Report comment"
                    className="shrink-0 text-muted-foreground hover:text-danger"
                  >
                    <Flag className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {new Date(comment.created_at).toLocaleString()}
                </p>
              </div>
            ))
          )}
        </div>

        <div className="mt-4 flex items-center gap-2 border-t border-border pt-4">
          <input
            type="text"
            value={commentText}
            onChange={(event) => setCommentText(event.target.value)}
            placeholder="Leave a comment..."
            className="h-11 flex-1 rounded-xl border border-input bg-surface px-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
          <Button size="md" loading={isPosting} disabled={!commentText.trim()} onClick={handlePost}>
            <Send className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </div>
  );
}

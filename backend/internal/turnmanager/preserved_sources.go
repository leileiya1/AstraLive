package turnmanager

import (
	c "astralive/backend/internal/contentplan/contract"
	"astralive/backend/internal/interaction"
	"context"
)

type PreservedSources struct{}

func (PreservedSources) SelectionSources(_ context.Context, v interaction.Selection) ([]c.CommentSource, error) {
	return SourcesFromEvents(v.Members)
}

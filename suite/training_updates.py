"""Shared native-graph accumulation; no model, device, or precision substitutions."""


def accumulated_update(torch, model, optimizer, rows, weights, logits_for, loss_for, lr):
    if not rows:
        raise ValueError('empty optimizer batch')
    optimizer.zero_grad(set_to_none=True)
    for group in optimizer.param_groups:
        group['lr'] = lr
    losses = []
    for row in rows:
        logits = logits_for(row)
        loss = loss_for(torch, logits, row['target'], weights[row['id']]) / len(rows)
        if not torch.isfinite(loss).item():
            raise ValueError('nonfinite training loss')
        loss.backward()
        losses.append(float(loss.detach()))
    norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
    optimizer.step()
    return {'weighted_loss': sum(losses), 'preclip_gradient_norm': float(norm), 'learning_rate_used': lr}
